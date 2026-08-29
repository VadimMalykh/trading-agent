defmodule FluxTrader.Trading.RiskManager do
  @moduledoc """
  The hard limits. Nothing reaches the exchange without passing through `check/1`.

  ## What is a hard limit and what is not

  M3_PLAN §6's last unchecked exit criterion is *"the policy never bypasses hard
  `RiskManager` limits"*, so it matters that the phrase means something specific. A **hard
  limit** here is a bound on exposure that exists to stop a loss becoming an incident:

    * how many positions may be open at once,
    * how large one position may be as a fraction of capital,
    * how much may be lost in a UTC day before trading stops,
    * how much leverage may be used.

  A **confidence floor is not one of them.** This module used to refuse anything under
  `confidence < 0.65`, which made it a fourth gate in series behind `serve.py`, the app and
  the policy — and M3_PLAN §3.1 settles that question the other way: **the policy owns
  coverage**, the serve gate is a reported diagnostic, and a confidence floor here could
  only ever *narrow* what the policy chose, never widen it. It survives as
  `min_confidence`, defaulting to `0.0`, purely as an operator override.

  ## Why the position cap defaults to 8 and not 3

  The old default was 3. M3-2 searched that exact knob over 36 configurations and found
  `max_concurrent=3` **worse than its uncapped twin in every single one**, on both pooled
  and worst-window net: the cap is not selecting trades, it is dropping whichever ones
  happen to arrive while three are already open. On eight pairs held serially — one position
  per pair, which the policy enforces independently — an uncapped policy is a real 8-slot
  portfolio, not leverage. So the default is one slot per served pair.

  It also has to be that way for the A/B to mean anything: the control arm is a ledger and
  cannot be refused, so a cap that throttles only the policy arm would show up as the policy
  underperforming when in fact it was being held back.

  ## Accounting that the old version was missing

  `open_positions` was incremented on approval and never decremented, and `daily_pnl` was
  never written at all — so both limits drifted out of contact with reality within an hour
  of uptime. `release/0` and `record_close/1` close that loop, and the daily loss counter
  resets on the UTC day boundary.
  """
  use GenServer
  require Logger

  def start_link(opts), do: GenServer.start_link(__MODULE__, opts, name: __MODULE__)

  @doc """
  Approve or refuse one order request.

  `request` needs `:symbol`, `:side` (`"BUY"`/`"SELL"`), `:price` and optionally `:size`
  (the policy's 1/3..5/3 multiplier, default 1.0) and `:confidence`.

  Returns `{:ok, order}` with quantity, leverage, stop and target filled in, or
  `{:reject, reason}`.
  """
  def check(request), do: GenServer.call(__MODULE__, {:check, request})

  @doc "Give a slot back when a position closes. Pair it with every approved `check/1`."
  def release, do: GenServer.cast(__MODULE__, :release)

  @doc "Book realised P&L, in quote currency, against the daily loss limit."
  def record_close(pnl) when is_number(pnl), do: GenServer.cast(__MODULE__, {:record_close, pnl})

  @doc "Reconcile the open-position count with the ledger, e.g. after a restart."
  def sync_open_positions(n) when is_integer(n) and n >= 0,
    do: GenServer.cast(__MODULE__, {:sync_open, n})

  def get_stats, do: GenServer.call(__MODULE__, :get_stats)

  @impl true
  def init(_opts) do
    config = Application.get_env(:fluxtrader, :trading, [])

    state = %{
      # The fallback derives from the priced universe rather than repeating a literal: a
      # cap narrower than the number of pairs we can charge a measured cost for is the
      # binding concurrency constraint T6 measured as costing net bps, and hard-coding 8
      # here would quietly reintroduce it the moment the config went missing.
      max_positions:
        Keyword.get(config, :max_positions, length(FluxTrader.Trading.ExecCost.measured_pairs())),
      # Base notional as a fraction of capital, before the policy's size multiplier.
      max_position_pct: Keyword.get(config, :max_position_pct, 0.10),
      # The ceiling the multiplier may not push a position through. 5/3 x 0.10 = 0.167 fits;
      # a base above 0.12 does not, and that is the point — the ladder must not be able to
      # turn an operator's sizing choice into an unbounded one.
      max_notional_pct: Keyword.get(config, :max_notional_pct, 0.20),
      stop_loss_pct: Keyword.get(config, :stop_loss_pct, 0.02),
      take_profit_ratio: Keyword.get(config, :take_profit_ratio, 2.0),
      leverage: Keyword.get(config, :leverage, 5),
      max_leverage: Keyword.get(config, :max_leverage, 10),
      max_daily_loss_pct: Keyword.get(config, :max_daily_loss_pct, 0.05),
      # Not a risk limit: see the moduledoc. 0.0 means the policy owns coverage.
      min_confidence: Keyword.get(config, :min_confidence, 0.0),
      total_capital: Keyword.get(config, :total_capital, 1000.0),
      daily_pnl: 0.0,
      day: Date.utc_today(),
      open_positions: 0,
      rejections: %{}
    }

    {:ok, state}
  end

  @impl true
  def handle_call({:check, request}, _from, state) do
    state = roll_day(state)
    size = Map.get(request, :size, 1.0)
    notional_pct = state.max_position_pct * size

    cond do
      state.leverage > state.max_leverage ->
        reject(state, :leverage_exceeded, "leverage #{state.leverage} > #{state.max_leverage}")

      Map.get(request, :confidence, 1.0) < state.min_confidence ->
        reject(state, :low_confidence, "confidence below operator floor #{state.min_confidence}")

      state.open_positions >= state.max_positions ->
        reject(state, :max_positions, "#{state.open_positions} open, cap #{state.max_positions}")

      notional_pct > state.max_notional_pct ->
        reject(
          state,
          :position_too_large,
          "#{Float.round(notional_pct * 100, 2)}% of capital > #{state.max_notional_pct * 100}%"
        )

      # Loss only. A day that is up 5% is not a reason to stop trading, and `abs/1` here
      # used to halt the system on a good day.
      state.daily_pnl <= -state.total_capital * state.max_daily_loss_pct ->
        reject(state, :daily_loss_limit, "daily P&L #{Float.round(state.daily_pnl, 2)}")

      true ->
        order =
          request
          |> Map.merge(%{
            quantity: state.total_capital * notional_pct / request.price * state.leverage,
            notional: state.total_capital * notional_pct * state.leverage,
            leverage: state.leverage,
            stop_loss: stop_loss(request, state),
            take_profit: take_profit(request, state)
          })

        {:reply, {:ok, order}, %{state | open_positions: state.open_positions + 1}}
    end
  end

  def handle_call(:get_stats, _from, state) do
    state = roll_day(state)

    {:reply,
     %{
       open_positions: state.open_positions,
       max_positions: state.max_positions,
       daily_pnl: state.daily_pnl,
       daily_loss_limit: -state.total_capital * state.max_daily_loss_pct,
       leverage: state.leverage,
       max_notional_pct: state.max_notional_pct,
       min_confidence: state.min_confidence,
       total_capital: state.total_capital,
       day: state.day,
       rejections: state.rejections
     }, state}
  end

  @impl true
  def handle_cast(:release, state) do
    {:noreply, %{state | open_positions: max(state.open_positions - 1, 0)}}
  end

  def handle_cast({:record_close, pnl}, state) do
    state = roll_day(state)
    {:noreply, %{state | daily_pnl: state.daily_pnl + pnl}}
  end

  def handle_cast({:sync_open, n}, state) do
    {:noreply, %{state | open_positions: n}}
  end

  defp roll_day(state) do
    today = Date.utc_today()
    if today == state.day, do: state, else: %{state | day: today, daily_pnl: 0.0}
  end

  defp reject(state, reason, detail) do
    Logger.info("RiskManager rejected: #{reason} (#{detail})")
    counts = Map.update(state.rejections, reason, 1, &(&1 + 1))
    {:reply, {:reject, reason}, %{state | rejections: counts}}
  end

  defp stop_loss(%{side: "BUY", price: p}, s), do: p * (1 - s.stop_loss_pct)
  defp stop_loss(%{side: "SELL", price: p}, s), do: p * (1 + s.stop_loss_pct)

  defp take_profit(%{side: "BUY", price: p}, s),
    do: p * (1 + s.stop_loss_pct * s.take_profit_ratio)

  defp take_profit(%{side: "SELL", price: p}, s),
    do: p * (1 - s.stop_loss_pct * s.take_profit_ratio)
end
