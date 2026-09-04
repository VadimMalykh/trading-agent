defmodule FluxTrader.Trading.ConfigTest do
  @moduledoc """
  Invariants on the SHIPPED trading configuration.

  These assert relationships between settings that are individually plausible and jointly
  wrong — the kind of mismatch that reads fine in a diff and only shows up in production.
  Deploy day 2026-08-28 produced three such defects in one afternoon; each of the checks
  below is one of those failure modes turned into a test.

  Deliberately `async: true` and free of any `Application.put_env`, so it reads what
  `config/config.exs` actually ships rather than a fixture. ExUnit runs async modules before
  synchronous ones, so a module that rewrites the trading config cannot race this.
  """
  use ExUnit.Case, async: true

  alias FluxTrader.Trading.{ExecCost, Policy, PolicyEngine}

  defp trading, do: Application.get_env(:fluxtrader, :trading, [])

  # The eight pairs the served checkpoint (seed 2, run 20260819T142759Z) was evaluated on,
  # and therefore the population its frozen cut was ranked over. Restated here because the
  # served universe is TWELVE, and that gap is a known, deliberate one rather than a mistake
  # — see the test below, which is written to describe it rather than to forbid it.
  @derivation_universe ~w(
    1000PEPEUSDT BTCUSDT DOGEUSDT ETHUSDT HYPEUSDT SOLUSDT WLDUSDT ZECUSDT
  )

  test "every served pair carries its own measured crossing cost" do
    # The invariant that gates how wide the universe may be. A served pair without its own
    # measurement is charged `@pooled`, a number pooled over the OTHER pairs — which for
    # ADAUSDT would have been 3.89 bps light.
    for pair <- PolicyEngine.served_pairs() do
      assert {tag, _bps} = ExecCost.round_trip_bps(pair)

      assert tag in [:measured, :measured_short_window],
             "#{pair} is served but has no measured crossing cost"
    end
  end

  test "the position cap is not narrower than the served universe" do
    # T6 re-tuned the concurrency cap over the pre-registered ladder on both universes and
    # `max_concurrent=none` won on both; every cap it tried cost net bps. A cap below the
    # universe size is not "one slot per pair" — it silently re-imposes the binding
    # constraint T6 measured at +13.21 net bps against +19.51 uncapped.
    assert Keyword.fetch!(trading(), :max_positions) >=
             MapSet.size(PolicyEngine.served_pairs())
  end

  test "the collector whitelist fallback is never narrower than the served universe" do
    # Deploy-day defect #2: narrowing the collector's list halted `orderbook_snapshots` on
    # four pairs for ~18 minutes, and collection gaps do not backfill. This list is only a
    # fallback (the DB row wins), but if that row is ever lost it is what the collector
    # subscribes to — so it must not be able to drop a pair we are trading, let alone one we
    # are merely collecting.
    whitelist = MapSet.new(Keyword.fetch!(trading(), :whitelist_pairs))

    assert MapSet.subset?(PolicyEngine.served_pairs(), whitelist),
           "served pairs missing from the whitelist fallback: " <>
             inspect(MapSet.difference(PolicyEngine.served_pairs(), whitelist))
  end

  test "served_pairs and the collector whitelist stay separate settings" do
    # They currently hold the same twelve pairs, which is exactly when someone is most
    # tempted to collapse them into one. They are different concerns: the whitelist may be
    # widened freely (collecting is cheap, not collecting is unrecoverable), while widening
    # served_pairs changes the coverage rank and therefore the rule.
    assert Keyword.has_key?(trading(), :served_pairs)
    assert Keyword.has_key?(trading(), :whitelist_pairs)
  end

  test "the served universe still contains every pair the frozen cut was derived on" do
    # 🔴 The invariant behind the 2026-08-31 freeze, in the only form that is actually true.
    #
    # `Policy.frozen_threshold/0` is the top-2% cut of the SERVED CHECKPOINT's (seed 2) own
    # evaluation split, which covers these eight pairs. Twelve are served. That is a known
    # gap: a fixed threshold stays well-defined on a wider universe — it describes this
    # model's confidence scale, not the pair list — but the realized coverage is no longer
    # exactly 2%. Closing it needs seed 2 re-evaluated on twelve pairs, which no dump exists
    # for, and which would also settle a parked pre-registration as a side effect.
    #
    # So this asserts the direction that MATTERS: the derivation universe must remain a
    # subset of what is served. Dropping one of these eight would mean the cut was ranked
    # over bars the policy can no longer trade, which is a different rule and not merely an
    # approximation of one.
    served = PolicyEngine.served_pairs()

    assert MapSet.subset?(MapSet.new(@derivation_universe), served),
           "the frozen cut was ranked over pairs that are no longer served: " <>
             inspect(MapSet.difference(MapSet.new(@derivation_universe), served))
  end

  test "the frozen constants are the ones backtest.py derived, to the last bit" do
    # Copied from a run of `backtest.py` over seed 2's split — the SERVED checkpoint,
    # `m2_multi_20260819T142759Z_a186182b.pt` — which reproduces that seed's arm A exactly:
    # 483 trades, mean size 1.362, entry confidence 0.6320 .. 0.7820.
    #
    # 🔴 Asserted as literals, and specifically NOT as a range. These are transcriptions
    # across two runtimes, and the failure modes worth catching are a typo, a well-meaning
    # round, and — the one that actually happened during this change — a constant taken from
    # a DIFFERENT CHECKPOINT. O8's cut of 0.5992 looks entirely plausible next to 0.6319 and
    # realizes 4.01% coverage on this model instead of 2%. Only an exact literal catches that.
    #
    # 🔵 2026-09-04: re-derived on the REPAIRED split (CANDLE_POLL_DEFECT.md; M3_PROTOCOL §9.2,
    # a data correction under C4, same checkpoint, same rule). Reproduces seed 2's arm A on
    # eval run 20260904T051921Z: 490 trades, mean size 1.367, entry confidence 0.6296 .. 0.7820.
    # Pre-repair values were 0.6318973898887634 and p80 0.025166796520352364.
    assert Policy.frozen_threshold() == 0.6296127438545227

    assert Policy.frozen_regime_edges() == [
             0.003956599626690149,
             0.00888611190021038,
             0.015089680440723896,
             0.025596268475055695
           ]

    assert Policy.frozen_ladder_p80() == 0.025596268475055695

    # The checkpoint both constants belong to: sha256 of
    # gs://fluxtrader-train-artifacts/checkpoints/m2_multi_20260819T142759Z_a186182b.pt.
    # `PolicyEngine` refuses to trade unless ml_inference reports exactly this.
    assert Policy.frozen_checkpoint_sha256() ==
             "882cd4153c2d2d401897aaca9e0ddc593a92b78a6baf71da5c229a154ab92d42"

    assert String.length(Policy.frozen_checkpoint_sha256()) == 64

    # Monotone, which `size_multiplier/2`'s `searchsorted` assumes and does not check.
    assert Policy.frozen_regime_edges() == Enum.sort(Policy.frozen_regime_edges())
  end

  test "the frozen cut spans every size bucket, so the ladder is not degenerate" do
    # backtest.py warns that a hard regime filter collapses sizing to a flat 5/3 and buys
    # nothing. The SIZED variant is only a distinct policy while all five buckets are
    # reachable, so assert the ladder still maps to 1/3 .. 5/3 across the frozen edges.
    edges = Policy.frozen_regime_edges()
    below = [hd(edges) / 2]
    above = [List.last(edges) * 2]
    probes = below ++ edges ++ above

    sizes = probes |> Enum.map(&Policy.size_multiplier(&1, edges)) |> Enum.uniq()
    assert length(sizes) == Policy.size_buckets()
    assert Enum.min(sizes) == 1 / 3
    assert Enum.max(sizes) == 5 / 3
  end
end
