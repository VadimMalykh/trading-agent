defmodule FluxTrader.Trading.LedgerTest do
  @moduledoc """
  The persistence layer the forward paper test accumulates in. The two things worth pinning
  are that the SQL coverage cut is the same arithmetic as the pure one, and that a closed
  trade books `gross - cost x size` exactly as `metrics.summarise` does — if the live ledger
  and the backtest disagree on the arithmetic, the A/B cannot be compared to M3_2_RESULTS.
  """
  use FluxTrader.DataCase, async: false

  alias FluxTrader.Trading.{Ledger, Policy}

  @horizon 240

  defp seed_bars(confidences, opts \\ []) do
    gated_above = Keyword.get(opts, :gated_above, 2.0)
    base = Keyword.get(opts, :base_ts, ~U[2026-08-28 00:00:00Z])

    confidences
    |> Enum.with_index()
    |> Enum.each(fn {conf, i} ->
      {:ok, _} =
        Ledger.record_bar(%{
          pair: "PAIR#{rem(i, 8)}",
          bar_ts: DateTime.add(base, -i * 300, :second),
          horizon_m: @horizon,
          confidence: conf,
          side: if(rem(i, 2) == 0, do: 1, else: -1),
          price: 100.0,
          gated: conf >= gated_above,
          regime: 0.01
        })
    end)
  end

  describe "record_bar/1" do
    test "is idempotent, so a 30-second poll cannot inflate the ranking population" do
      attrs = %{
        pair: "BTCUSDT",
        bar_ts: ~U[2026-08-28 10:05:00Z],
        horizon_m: @horizon,
        confidence: 0.7,
        side: 1,
        price: 100_000.0,
        gated: true,
        regime: 0.01
      }

      assert {:ok, _} = Ledger.record_bar(attrs)
      assert {:ok, _} = Ledger.record_bar(%{attrs | confidence: 0.9})
      assert Repo.aggregate(FluxTrader.Trading.PolicyBar, :count) == 1
    end
  end

  describe "coverage_threshold/3" do
    test "stays cold until the rank window holds a week of bars" do
      seed_bars(List.duplicate(0.5, 100))
      assert {:error, :cold, 100} = Ledger.coverage_threshold(0.02, @horizon, now())
    end

    test "agrees with Policy.coverage_threshold/2 on the same population" do
      confs =
        1..(Ledger.min_rank_bars() + 200)
        |> Enum.map(fn i -> 0.3 + rem(i * 7919, 6001) / 10_000 end)

      seed_bars(confs)

      assert {:ok, sql_thr, n} = Ledger.coverage_threshold(0.02, @horizon, now())
      assert n == length(confs)
      assert {:ok, pure_thr} = Policy.coverage_threshold(confs, 0.02)
      assert_in_delta sql_thr, pure_thr, 1.0e-12
    end

    test "only counts bars inside the rank window" do
      inside = List.duplicate(0.5, Ledger.min_rank_bars() + 10)
      seed_bars(inside)
      # A very old, very confident bar must not become the cut.
      {:ok, _} =
        Ledger.record_bar(%{
          pair: "OLD",
          bar_ts: DateTime.add(now(), -60 * 86_400, :second),
          horizon_m: @horizon,
          confidence: 0.99,
          side: 1,
          price: 1.0,
          gated: true
        })

      assert {:ok, thr, n} = Ledger.coverage_threshold(0.02, @horizon, now())
      assert n == length(inside)
      assert thr == 0.5
    end
  end

  describe "liveness/1" do
    test "reports how long the system has been correctly silent" do
      # The exact situation M3_PLAN §0.8 is worried about: bars keep arriving, none is
      # gated, and from outside that is indistinguishable from a dead process.
      seed_bars(List.duplicate(0.3, 50), gated_above: 2.0)

      live = Ledger.liveness(now())
      assert live.bars_last_24h > 0
      assert live.last_gated_at == nil
      assert live.seconds_since_last_gated == nil
      assert live.rank_window_days == Ledger.rank_window_days()
    end

    test "counts bars seen since the last gated signal" do
      seed_bars([0.9] ++ List.duplicate(0.3, 20), gated_above: 0.8)
      live = Ledger.liveness(now())
      # The gated bar is the newest of the seeded set (index 0 is the most recent).
      assert live.last_gated_at != nil
      assert live.bars_since_last_gated == 0
    end
  end

  describe "the paper ledger" do
    test "refuses a second open position on the same pair and arm — invariant 2" do
      assert {:ok, _} = Ledger.open_trade("policy", decision("BTCUSDT"))
      assert {:error, changeset} = Ledger.open_trade("policy", decision("BTCUSDT"))
      refute changeset.valid?
    end

    test "the two arms hold positions on the same pair independently" do
      assert {:ok, _} = Ledger.open_trade("policy", decision("BTCUSDT"))
      assert {:ok, _} = Ledger.open_trade("signal_only", decision("BTCUSDT"))
      assert MapSet.member?(Ledger.open_pairs("policy"), "BTCUSDT")
      assert MapSet.member?(Ledger.open_pairs("signal_only"), "BTCUSDT")
    end

    test "a closed position can be re-entered" do
      {:ok, t} = Ledger.open_trade("policy", decision("BTCUSDT"))
      {:ok, _} = Ledger.close_trade(t, 100_000.0)
      assert {:ok, _} = Ledger.open_trade("policy", decision("BTCUSDT"))
    end

    test "close_trade books gross - cost x size, with the pair's MEASURED cost" do
      {:ok, t} = Ledger.open_trade("policy", decision("BTCUSDT", side: 1, size: 5 / 3))
      # +30 bps gross move on a long.
      {:ok, closed} = Ledger.close_trade(t, 100_000.0 * 1.003)

      assert_in_delta closed.gross_bps, 30.0 * 5 / 3, 1.0e-6
      assert closed.cost_bps == 8.017
      assert_in_delta closed.net_bps, 30.0 * 5 / 3 - 8.017 * 5 / 3, 1.0e-6
      assert closed.status == "closed"
    end

    test "a short earns when the price falls" do
      {:ok, t} = Ledger.open_trade("policy", decision("ETHUSDT", side: -1))
      {:ok, closed} = Ledger.close_trade(t, 100_000.0 * 0.997)
      assert_in_delta closed.gross_bps, 30.0, 1.0e-6
      assert closed.cost_bps == 8.057
    end

    test "due_trades/1 returns only positions whose 4h hold has expired" do
      {:ok, _} = Ledger.open_trade("policy", decision("BTCUSDT"))
      assert Ledger.due_trades(~U[2026-08-28 12:00:00Z]) == []
      assert [_] = Ledger.due_trades(~U[2026-08-28 14:05:00Z])
    end
  end

  describe "arm_summary/2" do
    test "reports both readings of per-trade P&L, since the policy arm varies size" do
      # M3_2_RESULTS §D1 makes the same distinction about the offline +15.03 vs +11.24: the
      # per-trade mean is size-weighted, and quoting only it flatters a policy that sizes up.
      {:ok, a} = Ledger.open_trade("policy", decision("BTCUSDT", size: 5 / 3))
      {:ok, _} = Ledger.close_trade(a, 100_000.0 * 1.003)
      {:ok, b} = Ledger.open_trade("policy", decision("ETHUSDT", size: 1 / 3))
      {:ok, _} = Ledger.close_trade(b, 100_000.0 * 1.003)

      s = Ledger.arm_summary("policy")
      assert s.trades == 2
      assert_in_delta s.mean_size, 1.0, 1.0e-9
      # Sum of net over sum of size, not the mean of the per-trade means.
      expected_per_notional = (30.0 * 5 / 3 - 8.017 * 5 / 3 + (30.0 * 1 / 3 - 8.057 / 3)) / 2.0
      assert_in_delta s.net_bps_per_notional, expected_per_notional, 1.0e-6
    end

    test "an arm with no closed trades reports zero rather than crashing" do
      s = Ledger.arm_summary("signal_only")
      assert s.trades == 0
      assert s.net_bps == nil
      assert s.cum_net_bps == 0.0
    end

    test "drawdown is peak-to-trough of the net equity curve" do
      {:ok, a} = Ledger.open_trade("policy", decision("BTCUSDT"))
      {:ok, _} = Ledger.close_trade(a, 100_000.0 * 1.01, ~U[2026-08-28 14:05:00Z])
      {:ok, b} = Ledger.open_trade("policy", decision("ETHUSDT"))
      {:ok, _} = Ledger.close_trade(b, 100_000.0 * 0.98, ~U[2026-08-28 15:05:00Z])

      s = Ledger.arm_summary("policy")
      assert s.max_drawdown_bps < 0.0
      assert s.trades == 2
    end
  end

  defp now, do: ~U[2026-08-28 00:00:00Z]

  defp decision(pair, opts \\ []) do
    %{
      pair: pair,
      side: Keyword.get(opts, :side, 1),
      size: Keyword.get(opts, :size, 1.0),
      confidence: 0.8,
      threshold: 0.75,
      regime: 0.05,
      entry_price: 100_000.0,
      entry_ts: ~U[2026-08-28 10:05:00Z],
      exit_after_ts: ~U[2026-08-28 14:05:00Z]
    }
  end
end
