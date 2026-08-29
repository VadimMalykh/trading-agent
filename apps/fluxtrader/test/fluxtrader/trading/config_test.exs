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

  alias FluxTrader.Trading.{ExecCost, PolicyEngine}

  defp trading, do: Application.get_env(:fluxtrader, :trading, [])

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
end
