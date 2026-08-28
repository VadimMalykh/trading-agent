defmodule FluxTrader.Trading.PolicyTest do
  @moduledoc """
  The rule, pinned to the arithmetic that chose it.

  These are parity tests, not sanity checks: the fixtures in `FluxTrader.PolicyFixtures`
  come out of `ml/train/m3/backtest.py` itself. A failure here means the live policy has
  stopped being `cov0.02_hold240_rqnone_mcnone_SIZED`, which is a strategy change and
  M3_PROTOCOL §0 does not allow one against the same evidence.
  """
  use ExUnit.Case, async: true

  alias FluxTrader.PolicyFixtures, as: F
  alias FluxTrader.Trading.Policy

  describe "the spec is the one M3-2 selected" do
    test "coverage, hold and horizon are the searched values" do
      spec = Policy.spec()
      assert spec.coverage == 0.02
      assert spec.hold_minutes == 240
      assert spec.signal_horizon_m == 240
      # No concurrency cap: M3-2 found `max_concurrent=3` worse than its uncapped twin in
      # all 36 configurations.
      assert spec.max_concurrent == nil
      assert spec.size_by_regime
    end
  end

  describe "coverage_threshold/2 matches backtest.coverage_threshold" do
    for coverage <- [0.02, 0.05, 0.10] do
      test "at coverage #{coverage}" do
        c = unquote(coverage)
        {:ok, thr} = Policy.coverage_threshold(F.confidences(), c)
        assert_in_delta thr, F.confidence_thresholds()[c], 1.0e-12
      end

      test "selection at coverage #{coverage} is tie-inclusive and takes the same bars" do
        c = unquote(coverage)
        {:ok, thr} = Policy.coverage_threshold(F.confidences(), c)
        assert Enum.count(F.confidences(), &(&1 >= thr)) == F.selected_counts()[c]
      end
    end

    test "a tie at the boundary takes every bar at the cut, not an arbitrary one" do
      # torch.topk would pick one of the two 0.9s by kernel order. "Every bar at or above
      # the k-th largest" is the definition backtest.py settled on because it is the only
      # one that is deterministic and re-derivable.
      conf = [0.9, 0.9, 0.5, 0.4] ++ List.duplicate(0.1, 96)
      {:ok, thr} = Policy.coverage_threshold(conf, 0.01)
      assert thr == 0.9
      assert Enum.count(conf, &(&1 >= thr)) == 2
    end

    test "an empty or too-small population is an error, never a threshold of zero" do
      assert Policy.coverage_threshold([], 0.02) == {:error, :empty}
      # round(10 * 0.02) == 0 bars: no cut exists.
      assert Policy.coverage_threshold(List.duplicate(0.5, 10), 0.02) == {:error, :empty}
    end
  end

  describe "quintile_edges/1 matches pandas Series.quantile" do
    test "the four bar-quintile cuts" do
      {:ok, edges} = Policy.quintile_edges(F.regime_values())

      Enum.zip(edges, F.regime_edges())
      |> Enum.each(fn {got, want} -> assert_in_delta got, want, 1.0e-12 end)
    end
  end

  describe "size_multiplier/2 matches numpy.searchsorted(..., side=right)" do
    test "the 1/3 .. 5/3 ladder, including values exactly on an edge" do
      Enum.each(F.size_probes(), fn {value, want} ->
        assert_in_delta Policy.size_multiplier(value, F.regime_edges()), want, 1.0e-12
      end)
    end

    test "a value on an edge falls into the bucket above it" do
      edges = [1.0, 2.0, 3.0, 4.0]
      assert Policy.size_multiplier(0.5, edges) == 1 / 3
      assert Policy.size_multiplier(1.0, edges) == 2 / 3
      assert Policy.size_multiplier(4.0, edges) == 5 / 3
      assert Policy.size_multiplier(99.0, edges) == 5 / 3
    end
  end

  describe "bar_ts/1" do
    test "floors onto the 5-minute grid the model is scored on" do
      {:ok, ts, 0} = DateTime.from_iso8601("2026-08-28T10:07:43Z")
      assert Policy.bar_ts(ts) == ~U[2026-08-28 10:05:00Z]
    end

    test "a bar boundary is its own bar" do
      assert Policy.bar_ts(~U[2026-08-28 10:05:00Z]) == ~U[2026-08-28 10:05:00Z]
    end
  end

  describe "decide/3" do
    setup do
      %{
        bar: %{
          pair: "BTCUSDT",
          confidence: 0.80,
          side: 1,
          price: 100_000.0,
          ts: ~U[2026-08-28 10:05:00Z],
          gated: true
        },
        ctx: %{
          threshold: 0.75,
          regime: 0.05,
          regime_edges: [0.01, 0.02, 0.03, 0.04],
          open_pairs: MapSet.new(),
          open_count: 0
        }
      }
    end

    test "enters above the cut, on the model's side, sized by regime", %{bar: bar, ctx: ctx} do
      assert {:enter, d} = Policy.decide(bar, ctx)
      assert d.pair == "BTCUSDT"
      assert d.side == 1
      assert d.size == 5 / 3
      # The hold is four hours, and it is set at entry so a restart can still close it.
      assert d.exit_after_ts == ~U[2026-08-28 14:05:00Z]
    end

    test "skips below the cut", %{bar: bar, ctx: ctx} do
      assert {:skip, :below_coverage} = Policy.decide(%{bar | confidence: 0.74}, ctx)
    end

    test "the cut is inclusive at the boundary", %{bar: bar, ctx: ctx} do
      assert {:enter, _} = Policy.decide(%{bar | confidence: 0.75}, ctx)
    end

    test "one position per pair — invariant 2", %{bar: bar, ctx: ctx} do
      ctx = %{ctx | open_pairs: MapSet.new(["BTCUSDT"])}
      assert {:skip, :position_open} = Policy.decide(bar, ctx)
    end

    test "stays cold until there is a threshold to rank against", %{bar: bar, ctx: ctx} do
      assert {:skip, :warming_up} = Policy.decide(bar, %{ctx | threshold: nil})
    end

    test "a missing regime drops the bar rather than defaulting to size 1", %{bar: bar, ctx: ctx} do
      # backtest.py drops bars whose regime lookback is incomplete for the same reason: a
      # missing observable is not a neutral one.
      assert {:skip, :no_regime} = Policy.decide(bar, %{ctx | regime: nil})
      assert {:skip, :no_regime} = Policy.decide(bar, %{ctx | regime_edges: nil})
    end

    test "a flat model call is not a trade", %{bar: bar, ctx: ctx} do
      assert {:skip, :no_side} = Policy.decide(%{bar | side: 0}, ctx)
    end

    test "the concurrency cap binds only when one is configured", %{bar: bar, ctx: ctx} do
      ctx = %{ctx | open_count: 3}
      assert {:enter, _} = Policy.decide(Policy.spec(), bar, ctx)
      capped = %{Policy.spec() | max_concurrent: 3}
      assert {:skip, :max_concurrent} = Policy.decide(capped, bar, ctx)
    end
  end

  describe "decide_signal_only/3 — the A/B control" do
    setup do
      %{
        bar: %{
          pair: "ETHUSDT",
          confidence: 0.41,
          side: -1,
          price: 3_000.0,
          ts: ~U[2026-08-28 10:05:00Z],
          gated: true
        },
        ctx: %{open_pairs: MapSet.new(), regime: 0.05}
      }
    end

    test "enters on M2's own gate, at flat size", %{bar: bar, ctx: ctx} do
      assert {:enter, d} = Policy.decide_signal_only(bar, ctx)
      assert d.size == 1.0
      assert d.side == -1
      # Same hold as the policy arm, so the only difference between the ledgers is coverage
      # selection and sizing.
      assert d.exit_after_ts == ~U[2026-08-28 14:05:00Z]
    end

    test "ignores ungated bars however confident they look", %{bar: bar, ctx: ctx} do
      assert {:skip, :not_gated} = Policy.decide_signal_only(%{bar | gated: false}, ctx)
    end

    test "is serial per pair too", %{bar: bar, ctx: ctx} do
      ctx = %{ctx | open_pairs: MapSet.new(["ETHUSDT"])}
      assert {:skip, :position_open} = Policy.decide_signal_only(bar, ctx)
    end
  end
end
