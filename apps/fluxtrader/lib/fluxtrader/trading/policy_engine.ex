defmodule FluxTrader.Trading.PolicyEngine do
  @moduledoc """
  Where the M3 policy is actually connected to something.

  Until this module existed the milestone's output lived only in `ml/train/m3/`: nothing
  called the policy, so M3_PLAN §6's last exit criterion — *the policy never bypasses hard
  `RiskManager` limits* — could not even be tested. This is the loop that closes it.

  ## The path a bar takes

      SignalEngine broadcast
        -> floor to the 5-minute bar grid          (one decision per bar, not one per poll)
        -> record in policy_bars                   (the population the 2% rank is taken over)
        -> Policy.decide/3                         (the rule, expressed once)
        -> RiskManager.check/1                     (hard limits — never bypassed)
        -> Executor.open/3                         (crossing; paper in simulation mode)
        ... four hours later ...
        -> Executor.close/2 -> RiskManager.release/0 + record_close/1

  ## The A/B, and why the two arms are not symmetric

  Two ledgers run at once on the same bars (M3_PLAN §2 M3-5 item 4):

    * **`policy`** — the top 2% by confidence rank, regime-sized 1/3..5/3, 4h hold. It goes
      through `RiskManager` on every mode including `simulation`, so the risk path is
      exercised continuously rather than only on the day someone flips to `auto`.
    * **`signal_only`** — every bar M2's own gate approves, flat size, same 4h hold, same
      measured crossing cost. It is a **measurement arm**: it never produces an order and
      never consumes risk budget, because a control that could be refused for lack of a slot
      would make the policy look better than it is by throttling only its competitor.

  Both are charged the same per-pair cost, so the only difference between the two ledgers is
  coverage selection and sizing — which is exactly what the policy claims to add.

  ## Coverage lives here, and only here

  §3.1 was an architectural decision and this is where it landed: `serve.py` gates, the app
  used to gate again, and if the policy gated too there would be three gates in series and
  the policy could never *widen* coverage — only ever see bars M2 had already approved.
  **The policy owns coverage.** The serve gate is recorded on every bar as a diagnostic and
  as the control arm's entry condition, and it filters nothing.

  ## The served universe is NOT the collection whitelist

  `Settings.get_whitelist/0` is the list of pairs the **collector** subscribes to, and it is
  deliberately wider than the eight pairs M3 trades: collecting a pair costs a REST poll and
  a few MB a day, while *not* collecting it is unrecoverable — order-book history begins the
  day the collector is pointed at a pair and never backfills.

  The policy's universe is a different thing and it is pinned here, to
  `config :fluxtrader, :trading, served_pairs`. It must stay the eight pairs M3-2 measured
  the rule on and M3-4 measured a crossing cost for (T6 closed the 8-vs-12 question). Two
  distinct things break if the policy ranks over a wider set:

    * **the coverage cut.** "The top 2%" is a rank over a population, so adding four
      unmeasured pairs to that population silently changes the rule that M3-2 selected.
    * **the cost charged.** `ExecCost.round_trip_bps/1` has no measurement outside the eight
      and falls back to the pooled 9.842 — a number pooled over the *other* pairs.

  🔴 Do not fix a mismatch here by narrowing the collection whitelist. That stops collection
  on the excluded pairs, and the resulting gap cannot be backfilled. (Learned the hard way on
  2026-08-28: narrowing the whitelist to the served eight halted `orderbook_snapshots` on
  ADA/AVAX/LINK/XRP for ~18 minutes before it was caught.)
  """
  use GenServer
  require Logger

  alias FluxTrader.Trading.{ExecCost, Executor, Ledger, Policy, Regime, RiskManager}

  @policy_arm "policy"
  @control_arm "signal_only"
  @tick_ms 30_000
  @prune_every_ticks 2_880
  # A mark older than this is not good enough to close a position against.
  @stale_price_s 600

  def start_link(opts), do: GenServer.start_link(__MODULE__, opts, name: __MODULE__)

  @doc "Everything /api/health needs from the policy loop."
  def status do
    GenServer.call(__MODULE__, :status, 10_000)
  catch
    :exit, _ -> %{ok: false, error: "policy engine unavailable"}
  end

  @doc "Run one decision cycle now, instead of waiting for the tick. Used by tests and ops."
  def refresh, do: GenServer.call(__MODULE__, :tick, 60_000)

  @impl true
  def init(opts) do
    Phoenix.PubSub.subscribe(FluxTrader.PubSub, "signals:live")

    # `:autotick` and the two source functions exist so an integration test can drive the
    # whole path — bar to ledger row — without a live inference service and without waiting
    # out the seven-day rank-window warmup. In production all three take their defaults.
    if Keyword.get(opts, :autotick, true), do: Process.send_after(self(), :tick, 10_000)

    {:ok,
     %{
       spec: Keyword.get(opts, :spec, Policy.spec()),
       autotick: Keyword.get(opts, :autotick, true),
       signals_fun: Keyword.get(opts, :signals_fun, &__MODULE__.default_signals/0),
       regime_fun: Keyword.get(opts, :regime_fun, &__MODULE__.default_regime/0),
       threshold: nil,
       threshold_bars: 0,
       threshold_at: nil,
       prices: %{},
       decisions: %{},
       skips: %{},
       risk_rejections: %{},
       last_tick_at: nil,
       last_error: nil,
       ticks: 0
     }}
  end

  # A signal arriving between ticks only updates the mark. Decisions are taken on the tick so
  # that the whole bar is scored against one threshold rather than a moving one.
  @impl true
  def handle_info({:signal, %{symbol: sym, price: price}}, state) when is_number(price) do
    Executor.mark(sym, price)
    {:noreply, put_in(state.prices[sym], {price, DateTime.utc_now()})}
  end

  def handle_info({:signal, _}, state), do: {:noreply, state}

  def handle_info(:tick, state) do
    state =
      try do
        run_tick(state)
      rescue
        e ->
          Logger.error("policy tick failed: #{Exception.message(e)}")
          %{state | last_error: Exception.message(e)}
      end

    if state.autotick, do: Process.send_after(self(), :tick, @tick_ms)
    {:noreply, state}
  end

  def handle_info(_msg, state), do: {:noreply, state}

  @impl true
  def handle_call(:tick, _from, state) do
    state = run_tick(state)
    {:reply, :ok, state}
  end

  def handle_call(:status, _from, state) do
    {:reply,
     %{
       ok: state.last_error == nil,
       last_error: state.last_error,
       last_tick_at: state.last_tick_at,
       coverage: state.spec.coverage,
       served_pairs: served_pairs() |> Enum.sort(),
       hold_minutes: state.spec.hold_minutes,
       signal_horizon_m: state.spec.signal_horizon_m,
       confidence_threshold: state.threshold,
       rank_window_bars: state.threshold_bars,
       warm: state.threshold != nil,
       # Named skip counts since boot. A policy that is correctly sitting out a calm market
       # and a policy that is broken produce the same silence otherwise (§0.8).
       skips: state.skips,
       risk_rejections: state.risk_rejections,
       decisions: state.decisions
     }, state}
  end

  # ------------------------------------------------------------------ the cycle

  defp run_tick(state) do
    now = DateTime.utc_now()
    regime = state.regime_fun.()
    served = served_pairs()

    # Filtered BEFORE record_bars, not at entry: a bar that reaches policy_bars joins the
    # population the 2% rank is taken over, so an unserved pair recorded here would move the
    # cut even though it could never be traded.
    {bars, unserved} =
      state.signals_fun.()
      |> Enum.flat_map(&List.wrap(to_bar(&1, regime, now)))
      |> Enum.split_with(&served?(&1.pair, served))

    state = count_skips(state, :not_served, length(unserved))

    record_bars(state, bars)

    state =
      state
      |> refresh_threshold(now)
      |> close_due(now)
      |> open_new(bars)
      |> maybe_prune(now)

    %{state | last_tick_at: now, ticks: state.ticks + 1, last_error: nil}
  end

  @doc false
  def default_signals do
    case FluxTrader.ML.SignalEngine.latest() do
      %{signals: signals} when is_map(signals) -> Map.values(signals)
      _ -> []
    end
  catch
    :exit, _ -> []
  end

  @doc """
  The pairs the policy is allowed to rank and trade over — see the "served universe" note in
  the moduledoc. Defaults to the eight M3-2/M3-4 pairs; the collector's whitelist is wider
  and independent.
  """
  def served_pairs do
    Application.get_env(:fluxtrader, :trading, [])
    |> Keyword.get(:served_pairs, ExecCost.measured_pairs())
    |> MapSet.new()
  end

  defp served?(pair, served), do: MapSet.member?(served, String.upcase(to_string(pair)))

  @doc false
  def default_regime do
    case Regime.state() do
      {:ok, r} -> r
      {:error, :cold} -> nil
    end
  catch
    :exit, _ -> nil
  end

  # Record every bar, gated or not. The ranking population must be *all* bars, otherwise
  # "the top 2%" is the top 2% of the bars M2 already liked, which is a different rule.
  defp record_bars(state, bars) do
    Enum.each(bars, fn bar ->
      Ledger.record_bar(%{
        pair: bar.pair,
        bar_ts: bar.ts,
        horizon_m: state.spec.signal_horizon_m,
        confidence: bar.confidence,
        side: bar.side,
        price: bar.price,
        gated: bar.gated,
        regime: bar.regime
      })
    end)
  end

  defp refresh_threshold(state, now) do
    case Ledger.coverage_threshold(state.spec.coverage, state.spec.signal_horizon_m, now) do
      {:ok, thr, n} ->
        %{state | threshold: thr, threshold_bars: n, threshold_at: now}

      {:error, :cold, n} ->
        # Cold is a state, not an error: the rank window needs a week of bars before the top
        # 2% of it means anything, and until then the policy must not trade.
        %{state | threshold: nil, threshold_bars: n, threshold_at: now}
    end
  end

  # The open sets are read once per tick and updated as positions are taken, so a tick that
  # opens on eight pairs costs two queries rather than sixteen. The partial unique index is
  # still the authority — this is a fast path, not the invariant.
  defp open_new(state, bars) do
    open = %{
      @policy_arm => Ledger.open_pairs(@policy_arm),
      @control_arm => Ledger.open_pairs(@control_arm)
    }

    {state, _open} =
      Enum.reduce(bars, {state, open}, fn bar, {acc, open} ->
        {acc, open} = try_policy_arm(acc, bar, open)
        try_control_arm(acc, bar, open)
      end)

    state
  end

  defp try_policy_arm(state, bar, open) do
    ctx = %{
      threshold: state.threshold,
      regime: bar.regime,
      regime_edges: bar.regime_edges,
      open_pairs: open[@policy_arm],
      open_count: MapSet.size(open[@policy_arm])
    }

    case Policy.decide(state.spec, bar, ctx) do
      {:skip, reason} ->
        {count_skip(state, reason), open}

      {:enter, decision} ->
        risk_request = %{
          symbol: decision.pair,
          side: if(decision.side > 0, do: "BUY", else: "SELL"),
          price: decision.entry_price,
          size: decision.size,
          confidence: decision.confidence
        }

        case RiskManager.check(risk_request) do
          {:ok, order} ->
            decision =
              decision
              |> Map.put(:quantity, order[:quantity])
              |> Map.put(:notional, order[:notional])

            case Executor.open(@policy_arm, decision, order) do
              {:ok, _trade} ->
                {count_decision(state, :policy_opened),
                 Map.update!(open, @policy_arm, &MapSet.put(&1, decision.pair))}

              {:error, _} ->
                # The order did not open, so the slot RiskManager just reserved must go back.
                RiskManager.release()
                {count_decision(state, :policy_open_failed), open}
            end

          {:reject, reason} ->
            Logger.info("policy entry on #{decision.pair} refused by RiskManager: #{reason}")
            {%{state | risk_rejections: bump(state.risk_rejections, reason)}, open}
        end
    end
  end

  defp try_control_arm(state, bar, open) do
    ctx = %{open_pairs: open[@control_arm], regime: bar.regime}

    case Policy.decide_signal_only(state.spec, bar, ctx) do
      {:skip, _reason} ->
        {state, open}

      {:enter, decision} ->
        case Executor.open(@control_arm, decision) do
          {:ok, _} ->
            {count_decision(state, :control_opened),
             Map.update!(open, @control_arm, &MapSet.put(&1, decision.pair))}

          {:error, _} ->
            {state, open}
        end
    end
  end

  defp close_due(state, now) do
    now
    |> Ledger.due_trades()
    |> Enum.reduce(state, fn trade, acc ->
      case exit_price(acc, trade.pair) do
        {:ok, price} ->
          case Executor.close(trade, price) do
            {:ok, closed} ->
              if closed.arm == @policy_arm do
                RiskManager.release()
                # The daily-loss limit is a money limit, so bps have to be converted back
                # through the notional RiskManager itself approved at entry.
                if closed.notional,
                  do: RiskManager.record_close(closed.net_bps / 1.0e4 * closed.notional)
              end

              count_decision(acc, :closed)

            {:error, _} ->
              count_decision(acc, :close_failed)
          end

        {:error, _} ->
          # Leave it open and try again next tick. Closing at a stale or invented price
          # would put a fabricated number into the ledger the whole experiment is scored on.
          count_decision(acc, :close_deferred_no_price)
      end
    end)
  end

  # ------------------------------------------------------------------ bars and prices

  # Confidence and side come from the 240-minute head, which is the horizon M3-2 searched
  # and selected on. If a served checkpoint does not carry that head there is no policy to
  # run — falling back to another horizon would be running a different, unscored rule.
  defp to_bar(signal, regime, now) do
    h = to_string(Policy.signal_horizon_m())

    with %{} = horizons <- Map.get(signal, :horizons),
         %{} = head <- Map.get(horizons, h),
         conf when is_number(conf) <- get_in_any(head, "confidence"),
         dir when is_binary(dir) <- get_in_any(head, "direction"),
         price when is_number(price) <- Map.get(signal, :price) do
      %{
        pair: Map.get(signal, :symbol),
        ts: Policy.bar_ts(Map.get(signal, :timestamp) || now),
        confidence: conf * 1.0,
        side: side_of(dir),
        price: price * 1.0,
        gated: get_in_any(head, "gated") == true,
        regime: regime && regime.value,
        regime_edges: regime && regime.edges
      }
    else
      _ -> nil
    end
  end

  defp get_in_any(map, key) do
    Map.get(map, key) || Map.get(map, String.to_existing_atom(key))
  rescue
    ArgumentError -> Map.get(map, key)
  end

  defp side_of("up"), do: 1
  defp side_of("down"), do: -1
  defp side_of(_), do: 0

  defp exit_price(state, pair) do
    case Map.get(state.prices, pair) do
      {price, at} ->
        if DateTime.diff(DateTime.utc_now(), at) <= @stale_price_s,
          do: {:ok, price},
          else: fetch_price(pair)

      nil ->
        fetch_price(pair)
    end
  end

  defp fetch_price(pair) do
    case FluxTrader.Binance.Client.klines(pair, "1m", limit: 1) do
      {:ok, [[_t, _o, _h, _l, close | _] | _]} -> {:ok, to_float(close)}
      other -> {:error, other}
    end
  end

  defp to_float(v) when is_binary(v), do: String.to_float(v)
  defp to_float(v) when is_number(v), do: v * 1.0

  # ------------------------------------------------------------------ bookkeeping

  defp maybe_prune(state, now) do
    if rem(state.ticks, @prune_every_ticks) == 0 and state.ticks > 0 do
      n = Ledger.prune_bars(now)
      if n > 0, do: Logger.info("pruned #{n} policy bars past the retention window")
    end

    state
  end

  defp count_skip(state, reason), do: %{state | skips: bump(state.skips, reason)}

  defp count_skips(state, _reason, 0), do: state
  defp count_skips(state, reason, n), do: %{state | skips: Map.update(state.skips, reason, n, &(&1 + n))}
  defp count_decision(state, key), do: %{state | decisions: bump(state.decisions, key)}
  defp bump(map, key), do: Map.update(map, key, 1, &(&1 + 1))
end
