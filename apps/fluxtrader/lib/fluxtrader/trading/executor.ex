defmodule FluxTrader.Trading.Executor do
  @moduledoc """
  The order path. **It crosses the spread, and that is the whole design.**

  ## Why there are no limit orders in this file

  M3-4 measured both arms on 23 days of order-book history (`docs/M3_4_RESULTS.md`). Resting
  a limit order looks 3.60 bps cheaper round trip on the fee arithmetic — but the
  adverse-selection panel is negative in **16 of 16** (pair, direction) cells: a resting buy
  fills *because* the price came down through it, and then keeps going. The touch spread on
  BTC is 0.01 bps, so there is almost no spread to capture in the first place; what the
  maker arm collects in fees it hands straight back in the price path.

  So there is no queue model here, no fill probability, no chase logic and no partial-fill
  bookkeeping. M3_PLAN §0.8 item 3 states the consequence plainly: this is days of work M3-5
  does not have to do. If someone later wants the maker arm, that is a new study with a new
  protocol, not an edit to this module.

  ## Modes

    * `simulation` — the paper book. Entries and exits are ledger rows priced at the last
      traded price and charged M3-4's **measured per-pair** crossing cost. This is what the
      A/B runs on and it is the default.
    * `signal` — log the intent, book nothing.
    * `manual` — hold for approval.
    * `auto` — a real `MARKET` order on Binance USDⓈ-M. Crossing, because that is what the
      strategy was scored assuming.

  ## One deviation from the scored policy, stated out loud

  `RiskManager` attaches a stop and a target to every approved order. The M3-2 policy has
  **neither** — it was scored on a fixed four-hour hold and nothing else, and a barrier exit
  backtested against a fixed-horizon return is exactly the policy mismatch C4b was filed
  for. The paper arms therefore ignore both and close on the timer. On the `auto` path they
  are attached as a catastrophe brake, and that brake is an **unmeasured** deviation from
  the backtest: it must be priced (M3-0b's price path is what would let us price it) before
  real money goes near this.
  """
  use GenServer
  require Logger

  alias FluxTrader.Trading.{ExecCost, Ledger, PaperTrade}

  # The A/B's control arm is a measurement ledger and must never reach the exchange: it
  # exists to say what M2's raw gate would have earned, not to trade it.
  @paper_only_arms ["signal_only"]

  def start_link(opts), do: GenServer.start_link(__MODULE__, opts, name: __MODULE__)

  @doc """
  Open a position on `arm` from an approved order.

  The policy arm reaches this only after `RiskManager.check/1` has approved it — that is
  M3_PLAN §6's last exit criterion, and `risk_manager_test.exs` pins it.
  """
  def open(arm, decision, order \\ %{}) do
    GenServer.call(__MODULE__, {:open, arm, decision, order}, 30_000)
  end

  @doc "Close a position at `exit_price` and book its realised P&L."
  def close(%PaperTrade{} = trade, exit_price) do
    GenServer.call(__MODULE__, {:close, trade, exit_price}, 30_000)
  end

  @doc "Open positions, shaped for the dashboard. `pnl` is unrealised **net bps**, not currency."
  def get_positions do
    GenServer.call(__MODULE__, :get_positions, 10_000)
  end

  def mode, do: GenServer.call(__MODULE__, :mode)

  @impl true
  def init(_opts) do
    config = Application.get_env(:fluxtrader, :trading, [])
    mode = Keyword.get(config, :mode, "simulation")
    Logger.info("Executor starting in #{mode} mode (crossing only; no limit orders — M3-4)")

    if mode == "auto" do
      # `Binance.Client.post/2` sends neither an `X-MBX-APIKEY` header nor an HMAC-SHA256
      # signature, which Binance requires on every TRADE endpoint. A real order therefore
      # comes back 401 and the loop looks like it is trading while placing nothing. Say so
      # at boot rather than discovering it from an empty fill log.
      Logger.error(
        "TRADING_MODE=auto, but the order path is UNSIGNED — Binance.Client.post/2 sends no " <>
          "API key header and no HMAC signature, so /fapi/v1/order will reject every request. " <>
          "M3-5 delivers the PAPER A/B; request signing is not part of it. Use simulation."
      )
    end

    {:ok, %{mode: mode, marks: %{}}}
  end

  @impl true
  def handle_call(:mode, _from, state), do: {:reply, state.mode, state}

  def handle_call({:open, arm, decision, order}, _from, state) do
    {:reply, do_open(state.mode, arm, decision, order), state}
  end

  def handle_call({:close, trade, exit_price}, _from, state) do
    {:reply, do_close(state.mode, trade, exit_price), state}
  end

  def handle_call(:get_positions, _from, state) do
    positions =
      Enum.flat_map(PaperTrade.arms(), fn arm ->
        arm
        |> Ledger.open_trades()
        |> Enum.map(&to_display(&1, state.marks))
      end)

    {:reply, positions, state}
  end

  @impl true
  def handle_cast({:mark, pair, price}, state) do
    {:noreply, %{state | marks: Map.put(state.marks, pair, price)}}
  end

  @doc "Remember the last seen price for a pair, so open positions can be marked."
  def mark(pair, price) when is_number(price),
    do: GenServer.cast(__MODULE__, {:mark, pair, price})

  # ------------------------------------------------------------------ open

  defp do_open(mode, arm, decision, _order) when mode in ["simulation", "signal", "manual"] do
    # Every non-auto mode books the same paper row. `signal` and `manual` differ from
    # `simulation` in what they do about a REAL order, and none of them places one — the
    # measurement must keep running regardless, because the point of the forward test is to
    # accumulate independent days (§0.5.4) and a mode switch should not silence it.
    case Ledger.open_trade(arm, decision) do
      {:ok, trade} ->
        {tag, cost} = ExecCost.round_trip_bps(decision.pair)

        Logger.info(
          "[#{String.upcase(mode)}] OPEN #{arm} #{side_word(decision.side)} #{decision.pair} " <>
            "@ #{fmt(decision.entry_price)} size=#{fmt(decision.size)} " <>
            "conf=#{fmt(decision.confidence)} cost=#{fmt(cost)}bps(#{tag}) " <>
            "exit_after=#{decision.exit_after_ts}"
        )

        {:ok, trade}

      {:error, changeset} ->
        # The commonest cause is the partial unique index refusing a second open position on
        # a pair, which is invariant 2 doing its job rather than a fault.
        Logger.debug("open #{arm} #{decision.pair} refused: #{inspect(changeset.errors)}")
        {:error, changeset}
    end
  end

  defp do_open("auto", arm, decision, _order) when arm in @paper_only_arms do
    # Never route the control arm to the exchange, whatever the mode says.
    do_open("simulation", arm, decision, %{})
  end

  defp do_open("auto", arm, decision, order) do
    params = %{
      symbol: decision.pair,
      side: side_word(decision.side),
      quantity: Map.get(order, :quantity)
    }

    decision = Map.put(decision, :quantity, params.quantity)

    case FluxTrader.Binance.Client.place_order(params) do
      {:ok, resp} ->
        Logger.info("[AUTO] OPEN #{decision.pair} #{params.side} qty=#{params.quantity}")
        # The paper row is still written on the auto path: it is the ledger the A/B and
        # every M3_PROTOCOL §4 metric are computed from, and a real fill does not make the
        # measurement less necessary.
        result = Ledger.open_trade(arm, decision)
        _ = resp
        result

      {:error, reason} ->
        Logger.error("[AUTO] order failed for #{decision.pair}: #{inspect(reason)}")
        {:error, reason}
    end
  end

  # ------------------------------------------------------------------ close

  defp do_close("auto", %PaperTrade{arm: arm} = trade, exit_price) when arm in @paper_only_arms,
    do: do_close("simulation", trade, exit_price)

  defp do_close("auto", %PaperTrade{} = trade, exit_price) do
    # `reduce_only` so a close can never accidentally open the opposite position — the
    # quantity is the one RiskManager approved at entry and stored on the row.
    params = %{
      symbol: trade.pair,
      side: side_word(-trade.side),
      quantity: trade.quantity,
      reduce_only: true
    }

    case FluxTrader.Binance.Client.place_order(params) do
      {:ok, _resp} ->
        Ledger.close_trade(trade, exit_price)

      {:error, reason} ->
        Logger.error("[AUTO] close failed for #{trade.pair}: #{inspect(reason)}")
        {:error, reason}
    end
  end

  defp do_close(mode, %PaperTrade{} = trade, exit_price) do
    case Ledger.close_trade(trade, exit_price) do
      {:ok, closed} ->
        Logger.info(
          "[#{String.upcase(mode)}] CLOSE #{closed.arm} #{closed.pair} " <>
            "@ #{fmt(exit_price)} gross=#{fmt(closed.gross_bps)}bps " <>
            "cost=#{fmt(closed.cost_bps)}bps net=#{fmt(closed.net_bps)}bps"
        )

        {:ok, closed}

      other ->
        other
    end
  end

  # ------------------------------------------------------------------ helpers

  defp to_display(%PaperTrade{} = t, marks) do
    mark = Map.get(marks, t.pair)

    unrealised =
      if mark && t.entry_price > 0 do
        t.side * (mark / t.entry_price - 1.0) * t.size * 1.0e4 - (t.cost_bps || 0.0) * t.size
      else
        0.0
      end

    %{
      id: t.id,
      arm: t.arm,
      symbol: t.pair,
      side: side_word(t.side),
      entry_price: t.entry_price,
      size: t.size,
      quantity: t.size,
      status: :open,
      opened_at: t.entry_ts,
      exit_after: t.exit_after_ts,
      # Unrealised net bps at the last seen price, not currency. 0.0 means unmarked.
      pnl: unrealised
    }
  end

  defp side_word(side) when side > 0, do: "BUY"
  defp side_word(side) when side < 0, do: "SELL"

  defp fmt(nil), do: "-"
  defp fmt(x) when is_float(x), do: :erlang.float_to_binary(x, decimals: 4)
  defp fmt(x), do: to_string(x)
end
