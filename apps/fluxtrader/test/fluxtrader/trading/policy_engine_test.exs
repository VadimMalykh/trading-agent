defmodule FluxTrader.Trading.PolicyEngineTest do
  @moduledoc """
  The end-to-end wiring, which is the actual deliverable of M3-5: a model output becomes a
  bar, the bar becomes a coverage rank, the rank becomes a decision, the decision passes the
  hard risk limits, and four hours later it becomes a closed row with a P&L booked at the
  measured crossing cost.

  Driven with injected signal and regime sources so the path can be exercised without a live
  inference service. Everything between the injection points is the production code.

  Since the 2026-08-31 freeze the coverage cut is `Policy.frozen_threshold/0`, so a test's
  confidences are compared against **that constant** rather than against whatever the fixture
  bars happened to rank to. `warm_the_rank_window/1` therefore no longer gates anything; it
  survives because the trailing rank is still computed as a drift diagnostic and one test
  reads it.
  """
  use FluxTrader.DataCase, async: false

  alias FluxTrader.Trading.{Executor, Ledger, PaperTrade, Policy, PolicyEngine, RiskManager}

  @horizon 240

  setup do
    prev = Application.get_env(:fluxtrader, :trading, [])
    on_exit(fn -> Application.put_env(:fluxtrader, :trading, prev) end)

    Application.put_env(:fluxtrader, :trading,
      mode: "simulation",
      max_positions: 12,
      max_position_pct: 0.10,
      max_notional_pct: 0.20,
      max_daily_loss_pct: 0.05,
      leverage: 5,
      max_leverage: 10,
      min_confidence: 0.0,
      total_capital: 1000.0
    )

    start_supervised!({Executor, []})
    start_supervised!({RiskManager, []})
    :ok
  end

  # A week of bars spread evenly over 0.40..0.89. Before the freeze this made the engine warm
  # and set the cut near 0.89; now it only populates the DIAGNOSTIC trailing rank, and no
  # test's entry decision depends on it.
  defp fill_the_diagnostic_window(now) do
    rows =
      for i <- 1..(Ledger.min_rank_bars() + 50) do
        %{
          pair: "FILL#{rem(i, 8)}",
          bar_ts: DateTime.add(now, -i * 60, :second) |> DateTime.truncate(:second),
          horizon_m: @horizon,
          confidence: 0.40 + rem(i, 50) / 100.0,
          side: 1,
          price: 1.0,
          gated: false,
          inserted_at: NaiveDateTime.utc_now() |> NaiveDateTime.truncate(:second)
        }
      end

    Repo.insert_all(FluxTrader.Trading.PolicyBar, rows)
  end

  defp signal(opts) do
    %{
      symbol: Keyword.fetch!(opts, :symbol),
      price: Keyword.get(opts, :price, 100_000.0),
      timestamp: Keyword.get(opts, :ts, DateTime.utc_now()),
      horizons: %{
        "240" => %{
          "direction" => Keyword.get(opts, :direction, "up"),
          "confidence" => Keyword.fetch!(opts, :confidence),
          "gated" => Keyword.get(opts, :gated, false)
        }
      }
    }
  end

  # The checkpoint-binding guard is satisfied by default: tests inject the frozen hash as
  # what inference "loaded", exactly as a correctly promoted VM would report it.
  defp start_engine(signals, regime, checkpoint \\ Policy.frozen_checkpoint_sha256()) do
    start_supervised!(
      {PolicyEngine,
       [
         autotick: false,
         signals_fun: fn -> signals end,
         regime_fun: fn -> regime end,
         checkpoint_fun: fn -> checkpoint end
       ]}
    )
  end

  # The ladder in force, not an invented one: `Regime.state/0` returns exactly this, so a
  # test that injected round numbers would be sizing against a ladder nothing serves.
  defp regime(value) do
    %{value: value, edges: Policy.frozen_regime_edges(), samples: 8640}
  end

  test "a top-2% bar becomes an approved, risk-checked, correctly sized paper position" do
    now = DateTime.utc_now()
    fill_the_diagnostic_window(now)

    start_engine([signal(symbol: "BTCUSDT", confidence: 0.95)], regime(0.05))
    :ok = PolicyEngine.refresh()

    status = PolicyEngine.status()
    assert status.warm
    assert status.decisions[:policy_opened] == 1

    assert [trade] = Ledger.open_trades("policy")
    assert trade.pair == "BTCUSDT"
    assert trade.side == 1
    # Regime 0.05 is above the top edge, so the top bucket: 5/3.
    assert_in_delta trade.size, 5 / 3, 1.0e-9
    # The cost stamped on the row is BTC's MEASURED round trip, not the old 14 bps.
    assert trade.cost_bps == 8.017
    # The hold is four hours from the bar, set at entry so a restart can still close it.
    assert DateTime.diff(trade.exit_after_ts, trade.entry_ts) == Policy.hold_minutes() * 60
    # It went through the risk manager: that is M3_PLAN §6's last exit criterion.
    assert %{open_positions: 1} = RiskManager.get_stats()
    assert trade.notional
    # Provenance (M3_PROTOCOL §9.6): the row names the rule that took it.
    assert trade.checkpoint == Policy.frozen_checkpoint_sha256()
    assert trade.ladder_p80 == Policy.frozen_ladder_p80()
    assert status.checkpoint_bound
  end

  test "the checkpoint-binding guard: a different checkpoint trades nothing, loudly" do
    now = DateTime.utc_now()
    fill_the_diagnostic_window(now)

    other = String.duplicate("ab", 32)
    start_engine([signal(symbol: "BTCUSDT", confidence: 0.95)], regime(0.05), other)
    :ok = PolicyEngine.refresh()

    status = PolicyEngine.status()
    refute status.checkpoint_bound
    assert status.checkpoint == other
    assert status.frozen_checkpoint == Policy.frozen_checkpoint_sha256()
    assert status.skips[:checkpoint_mismatch] == 1
    refute Map.has_key?(status.decisions, :policy_opened)
    assert Ledger.open_trades("policy") == []
    assert Ledger.open_trades("flat_size") == []
    # The bar is still recorded: the guard stops entries, not the evidence.
    assert Repo.aggregate(FluxTrader.Trading.PolicyBar, :count) > Ledger.min_rank_bars()
  end

  test "the checkpoint-binding guard: an unreadable checkpoint is unverified, not bound" do
    start_engine([signal(symbol: "BTCUSDT", confidence: 0.95)], regime(0.05), nil)
    :ok = PolicyEngine.refresh()

    status = PolicyEngine.status()
    refute status.checkpoint_bound
    assert status.skips[:checkpoint_unverified] == 1
    assert Ledger.open_trades("policy") == []
  end

  test "the retrain trigger reads the served checkpoint's own arrival record" do
    now = DateTime.utc_now()
    fill_the_diagnostic_window(now)

    start_engine([signal(symbol: "BTCUSDT", confidence: 0.95)], regime(0.05))
    :ok = PolicyEngine.refresh()

    trig = PolicyEngine.status().retrain_trigger
    assert trig.n_days == Policy.retrain_trigger_days()
    # The 0.95 bar just recorded meets the cut, so the trigger cannot have fired.
    assert trig.last_cut_exceeded_at
    assert trig.days_since < 1
    refute trig.fired
  end

  test "a pair outside the served universe never reaches policy_bars or a trade" do
    now = DateTime.utc_now()
    fill_the_diagnostic_window(now)

    # BNBUSDT is neither served nor measured: ExecCost has no crossing cost for it, so it
    # would be charged a number pooled from other pairs. It must not join the ranking
    # population, because "the top 2%" is a rank over that population.
    #
    # (This test used ADAUSDT until 2026-08-29, when ADA became one of the served twelve.)
    start_engine(
      [
        signal(symbol: "BNBUSDT", confidence: 0.99),
        signal(symbol: "BTCUSDT", confidence: 0.95)
      ],
      regime(0.05)
    )

    :ok = PolicyEngine.refresh()
    status = PolicyEngine.status()

    assert status.skips[:not_served] == 1
    refute Enum.any?(Ledger.open_trades("policy"), &(&1.pair == "BNBUSDT"))
    refute Enum.any?(Ledger.open_trades("flat_size"), &(&1.pair == "BNBUSDT"))
    assert Enum.any?(Ledger.open_trades("policy"), &(&1.pair == "BTCUSDT"))

    # And it is absent from the ranking population itself, not merely refused at entry.
    recorded = FluxTrader.Repo.all(FluxTrader.Trading.PolicyBar) |> Enum.map(& &1.pair)
    refute "BNBUSDT" in recorded
    assert "BTCUSDT" in recorded
  end

  test "the served universe is exactly the measured pairs, and none falls back to pooled" do
    served = PolicyEngine.served_pairs()

    assert MapSet.size(served) == 12
    assert MapSet.equal?(served, MapSet.new(FluxTrader.Trading.ExecCost.measured_pairs()))

    # This is the invariant the universe width actually turns on: no served pair may fall
    # back to the pooled cost, because that number is pooled over the OTHER pairs. Both
    # measured tags are acceptable — a pair's own 14-day measurement beats a constant
    # borrowed from eight different pairs — but `:pooled_fallback` is not.
    for pair <- served do
      assert {tag, _} = FluxTrader.Trading.ExecCost.round_trip_bps(pair)
      assert tag in [:measured, :measured_short_window]
    end
  end

  test "the frozen cut has no warmup: the very first bar can trade" do
    # 🔴 This test asserts the OPPOSITE of the one it replaced, and that is the 2026-08-31
    # freeze. A cut re-derived from a trailing rank needs a population to rank against, so
    # the policy used to sit out its first ~14 hours; a constant needs nothing. No bars are
    # seeded here at all.
    start_engine([signal(symbol: "BTCUSDT", confidence: 0.99)], regime(0.05))
    :ok = PolicyEngine.refresh()

    status = PolicyEngine.status()
    assert status.warm
    assert status.confidence_threshold == Policy.frozen_threshold()
    refute Map.has_key?(status.skips, :warming_up)
    assert [%{pair: "BTCUSDT"}] = Ledger.open_trades("policy")
  end

  test "the cut in force is the constant, and the trailing rank is only reported" do
    now = DateTime.utc_now()
    fill_the_diagnostic_window(now)

    # The seeded bars rank to a cut near 0.89 — far above the frozen 0.6319. If the trailing
    # rank were still deciding, a 0.70 bar would be skipped as `below_coverage`.
    start_engine([signal(symbol: "BTCUSDT", confidence: 0.70)], regime(0.05))
    :ok = PolicyEngine.refresh()

    status = PolicyEngine.status()
    assert status.confidence_threshold == Policy.frozen_threshold()
    assert status.rolling_threshold > 0.80
    assert status.rolling_threshold != status.confidence_threshold
    assert status.rank_window_bars >= Ledger.min_rank_bars()

    # The constant decided, not the window.
    assert [%{pair: "BTCUSDT"}] = Ledger.open_trades("policy")
  end

  test "a thin diagnostic window reports nil and holds nothing up" do
    # Cold used to mean "do not trade". It now means "this one number is not meaningful yet".
    start_engine([signal(symbol: "BTCUSDT", confidence: 0.99)], regime(0.05))
    :ok = PolicyEngine.refresh()

    status = PolicyEngine.status()
    assert status.rolling_threshold == nil
    assert status.warm
    assert length(Ledger.open_trades("policy")) == 1
  end

  test "a calm market is silent, and the silence is legible as correct" do
    # M3_PLAN §0.8's distinction, restated for the frozen rule. August 2026's confidence
    # never exceeded 0.569 against a cut of 0.6319, so the validated policy takes NOTHING all
    # month. That must not look like a broken engine: the bar is recorded, the skip is named
    # and counted, and the endpoint still reports the cut being applied.
    start_engine([signal(symbol: "BTCUSDT", confidence: 0.5616)], regime(0.05))
    :ok = PolicyEngine.refresh()

    status = PolicyEngine.status()
    assert status.skips[:below_coverage] == 1
    assert status.warm
    assert status.confidence_threshold == Policy.frozen_threshold()
    assert Ledger.open_trades("policy") == []

    # 0.5616 is the highest confidence the live ledger's first twelve trades entered on. Every
    # one of them was below the fixed cut, which is what made them trades of a different rule.
    assert 0.5616 < Policy.frozen_threshold()
  end

  test "an unremarkable bar is recorded but not traded" do
    now = DateTime.utc_now()
    fill_the_diagnostic_window(now)

    start_engine([signal(symbol: "BTCUSDT", confidence: 0.42)], regime(0.05))
    :ok = PolicyEngine.refresh()

    assert PolicyEngine.status().skips[:below_coverage] == 1
    assert Ledger.open_trades("policy") == []
    # It still enters the ranking population — "the top 2%" has to be over ALL bars.
    assert Repo.aggregate(
             from(b in FluxTrader.Trading.PolicyBar, where: b.pair == "BTCUSDT"),
             :count
           ) == 1
  end

  test "the two arms take the same bars and differ only in size" do
    # 🔴 The re-registered A/B, end to end. This test replaces one that asserted each arm
    # took bars the other refused — which was the OLD control, keyed off M2's gate. That arm
    # could not produce data (nothing gated in 8,184 bars), so the comparison it defined was
    # never going to happen. The control now answers the question the policy actually claims
    # to answer: is the regime ladder worth anything?
    now = DateTime.utc_now()
    fill_the_diagnostic_window(now)

    signals = [
      # Above the frozen cut. M2's gate is OFF on both, which used to mean the control took
      # neither; now the gate is irrelevant to entry and both arms take both.
      signal(symbol: "BTCUSDT", confidence: 0.97, gated: false),
      signal(symbol: "ETHUSDT", confidence: 0.70, gated: false),
      # Below the cut. Neither arm may take it — a control that took this would be trading
      # bars the policy rejects, and the ledgers would stop being comparable.
      signal(symbol: "SOLUSDT", confidence: 0.55, gated: true)
    ]

    start_engine(signals, regime(0.025))
    :ok = PolicyEngine.refresh()

    both = MapSet.new(["BTCUSDT", "ETHUSDT"])
    assert Ledger.open_pairs("policy") == both
    assert Ledger.open_pairs("flat_size") == both

    # The control is flat by definition; the policy is regime-sized. regime 0.025 sits in the
    # frozen ladder's fourth bucket, just below the 0.0252 top edge.
    for t <- Ledger.open_trades("flat_size"), do: assert(t.size == 1.0)
    for t <- Ledger.open_trades("policy"), do: assert_in_delta(t.size, 4 / 3, 1.0e-9)

    # Same entries, right down to the price and the exit deadline: size is the ONLY thing
    # that may differ, and asserting it field by field is what keeps this a one-variable
    # comparison as the code changes around it.
    p = Ledger.open_trades("policy") |> Enum.sort_by(& &1.pair)
    c = Ledger.open_trades("flat_size") |> Enum.sort_by(& &1.pair)

    for {a, b} <- Enum.zip(p, c) do
      assert a.pair == b.pair
      assert a.side == b.side
      assert a.entry_price == b.entry_price
      assert a.entry_ts == b.entry_ts
      assert a.exit_after_ts == b.exit_after_ts
      assert a.confidence == b.confidence
      refute a.size == b.size
    end
  end

  test "the control arm never consumes risk budget" do
    # It is a measurement arm. A control that could be refused for lack of a slot would
    # flatter the policy by throttling only its competitor, so the control must open its
    # position even when every slot is gone.
    now = DateTime.utc_now()
    fill_the_diagnostic_window(now)

    Application.put_env(
      :fluxtrader,
      :trading,
      Keyword.put(Application.get_env(:fluxtrader, :trading), :max_positions, 0)
    )

    stop_supervised!(RiskManager)
    start_supervised!({RiskManager, []})

    start_engine([signal(symbol: "BTCUSDT", confidence: 0.97)], regime(0.05))
    :ok = PolicyEngine.refresh()

    assert PolicyEngine.status().risk_rejections[:max_positions] == 1
    assert Ledger.open_trades("policy") == []
    # ...and the control took it anyway.
    assert [c] = Ledger.open_trades("flat_size")
    assert c.size == 1.0
    assert %{open_positions: 0} = RiskManager.get_stats()
  end

  test "a second bar on an open pair is ignored — no overlapping 4h holds" do
    now = DateTime.utc_now()
    fill_the_diagnostic_window(now)

    start_engine([signal(symbol: "BTCUSDT", confidence: 0.95)], regime(0.05))
    :ok = PolicyEngine.refresh()
    :ok = PolicyEngine.refresh()

    assert length(Ledger.open_trades("policy")) == 1
    assert PolicyEngine.status().skips[:position_open] >= 1
  end

  test "the hold expires, the position closes at the marked price, and the slot comes back" do
    now = DateTime.utc_now()
    fill_the_diagnostic_window(now)

    # The signal is served once, so the second tick closes without re-entering. (Re-entering
    # on the same bar as the exit is what `backtest.py` does — it retires expired positions
    # before considering entries — but it would obscure what this test is checking.)
    {:ok, box} = Agent.start_link(fn -> [signal(symbol: "BTCUSDT", confidence: 0.95)] end)

    pid =
      start_supervised!(
        {PolicyEngine,
         [
           autotick: false,
           signals_fun: fn -> Agent.get_and_update(box, fn s -> {s, []} end) end,
           regime_fun: fn -> regime(0.05) end,
           checkpoint_fun: fn -> Policy.frozen_checkpoint_sha256() end
         ]}
      )

    :ok = PolicyEngine.refresh()
    assert [trade] = Ledger.open_trades("policy")
    assert %{open_positions: 1} = RiskManager.get_stats()

    # Mark the pair 30 bps up, the way a live signal broadcast would.
    send(pid, {:signal, %{symbol: "BTCUSDT", price: 100_000.0 * 1.003}})
    # Bring the 4h hold forward instead of waiting four hours.
    past = DateTime.utc_now() |> DateTime.add(-1, :second) |> DateTime.truncate(:second)

    trade
    |> Ecto.Changeset.change(exit_after_ts: past)
    |> Repo.update!()

    :ok = PolicyEngine.refresh()

    assert Ledger.open_trades("policy") == []
    closed = Repo.get!(PaperTrade, trade.id)
    assert closed.status == "closed"
    # gross - cost x size, exactly as metrics.summarise books it.
    assert_in_delta closed.gross_bps, 30.0 * 5 / 3, 1.0e-3
    assert_in_delta closed.net_bps, 30.0 * 5 / 3 - 8.017 * 5 / 3, 1.0e-3
    # The slot went back to the risk manager and the P&L was booked against the daily limit.
    assert %{open_positions: 0} = RiskManager.get_stats()
    assert RiskManager.get_stats().daily_pnl > 0.0
  end

  test "when the risk manager refuses, nothing is opened and the refusal is counted" do
    now = DateTime.utc_now()
    fill_the_diagnostic_window(now)

    Application.put_env(
      :fluxtrader,
      :trading,
      Keyword.put(Application.get_env(:fluxtrader, :trading), :max_positions, 0)
    )

    stop_supervised!(RiskManager)
    start_supervised!({RiskManager, []})

    start_engine([signal(symbol: "BTCUSDT", confidence: 0.95)], regime(0.05))
    :ok = PolicyEngine.refresh()

    assert Ledger.open_trades("policy") == []
    assert PolicyEngine.status().risk_rejections[:max_positions] == 1
  end

  test "a bar with no 240-minute head is dropped rather than run on another horizon" do
    now = DateTime.utc_now()
    fill_the_diagnostic_window(now)

    wrong_horizon = %{
      symbol: "BTCUSDT",
      price: 100_000.0,
      timestamp: DateTime.utc_now(),
      horizons: %{"60" => %{"direction" => "up", "confidence" => 0.99, "gated" => true}}
    }

    start_engine([wrong_horizon], regime(0.05))
    :ok = PolicyEngine.refresh()

    # Falling back to another head would be running a different, unscored rule.
    assert Ledger.open_trades("policy") == []

    assert Repo.aggregate(
             from(b in FluxTrader.Trading.PolicyBar, where: b.pair == "BTCUSDT"),
             :count
           ) == 0
  end

  test "the policy will not size on a cold regime" do
    now = DateTime.utc_now()
    fill_the_diagnostic_window(now)

    start_engine([signal(symbol: "BTCUSDT", confidence: 0.95)], nil)
    :ok = PolicyEngine.refresh()

    assert PolicyEngine.status().skips[:no_regime] == 1
    assert Ledger.open_trades("policy") == []
  end
end
