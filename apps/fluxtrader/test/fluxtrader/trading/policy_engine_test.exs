defmodule FluxTrader.Trading.PolicyEngineTest do
  @moduledoc """
  The end-to-end wiring, which is the actual deliverable of M3-5: a model output becomes a
  bar, the bar becomes a coverage rank, the rank becomes a decision, the decision passes the
  hard risk limits, and four hours later it becomes a closed row with a P&L booked at the
  measured crossing cost.

  Driven with injected signal and regime sources so the path can be exercised without a live
  inference service and without waiting out the seven-day rank-window warmup. Everything
  between the injection points is the production code.
  """
  use FluxTrader.DataCase, async: false

  alias FluxTrader.Trading.{Executor, Ledger, PaperTrade, Policy, PolicyEngine, RiskManager}

  @horizon 240

  setup do
    prev = Application.get_env(:fluxtrader, :trading, [])
    on_exit(fn -> Application.put_env(:fluxtrader, :trading, prev) end)

    Application.put_env(:fluxtrader, :trading,
      mode: "simulation",
      max_positions: 8,
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

  # A week of bars spread evenly over 0.40..0.89, so the rank window is warm and its top-2%
  # cut lands near 0.89 — above anything M2's own gate would call ordinary, below the very
  # confident bars the tests inject.
  defp warm_the_rank_window(now) do
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

  defp start_engine(signals, regime) do
    start_supervised!(
      {PolicyEngine,
       [
         autotick: false,
         signals_fun: fn -> signals end,
         regime_fun: fn -> regime end
       ]}
    )
  end

  defp regime(value) do
    %{value: value, edges: [0.01, 0.02, 0.03, 0.04], samples: 8640}
  end

  test "a top-2% bar becomes an approved, risk-checked, correctly sized paper position" do
    now = DateTime.utc_now()
    warm_the_rank_window(now)

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
  end

  test "the policy stays cold, and says why, until the rank window has a week of bars" do
    # The distinction M3_PLAN §0.8 asks for: correct silence must be legible as correct.
    start_engine([signal(symbol: "BTCUSDT", confidence: 0.99)], regime(0.05))
    :ok = PolicyEngine.refresh()

    status = PolicyEngine.status()
    refute status.warm
    assert status.skips[:warming_up] == 1
    assert Ledger.open_trades("policy") == []
  end

  test "an unremarkable bar is recorded but not traded" do
    now = DateTime.utc_now()
    warm_the_rank_window(now)

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

  test "the control arm trades M2's gate while the policy arm ignores it, and vice versa" do
    now = DateTime.utc_now()
    warm_the_rank_window(now)

    signals = [
      # Gated by M2 but nowhere near the top 2%: the control takes it, the policy does not.
      signal(symbol: "ETHUSDT", confidence: 0.60, gated: true),
      # Top 2% but M2's gate said no: the policy takes it, the control does not. This is the
      # coverage-widening §3.1 exists to make possible.
      signal(symbol: "BTCUSDT", confidence: 0.97, gated: false)
    ]

    start_engine(signals, regime(0.025))
    :ok = PolicyEngine.refresh()

    assert Ledger.open_pairs("policy") == MapSet.new(["BTCUSDT"])
    assert Ledger.open_pairs("signal_only") == MapSet.new(["ETHUSDT"])
    # The control is flat-sized by definition; the policy is regime-sized.
    assert [control] = Ledger.open_trades("signal_only")
    assert control.size == 1.0
    assert [policy] = Ledger.open_trades("policy")
    assert_in_delta policy.size, 1.0, 1.0e-9
  end

  test "a second bar on an open pair is ignored — no overlapping 4h holds" do
    now = DateTime.utc_now()
    warm_the_rank_window(now)

    start_engine([signal(symbol: "BTCUSDT", confidence: 0.95)], regime(0.05))
    :ok = PolicyEngine.refresh()
    :ok = PolicyEngine.refresh()

    assert length(Ledger.open_trades("policy")) == 1
    assert PolicyEngine.status().skips[:position_open] >= 1
  end

  test "the hold expires, the position closes at the marked price, and the slot comes back" do
    now = DateTime.utc_now()
    warm_the_rank_window(now)

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
           regime_fun: fn -> regime(0.05) end
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
    warm_the_rank_window(now)

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
    warm_the_rank_window(now)

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
    warm_the_rank_window(now)

    start_engine([signal(symbol: "BTCUSDT", confidence: 0.95)], nil)
    :ok = PolicyEngine.refresh()

    assert PolicyEngine.status().skips[:no_regime] == 1
    assert Ledger.open_trades("policy") == []
  end
end
