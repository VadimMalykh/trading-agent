defmodule FluxTraderWeb.HealthController do
  use FluxTraderWeb, :controller

  @moduledoc """
  `/api/health` — one place to answer "is this thing working, and if it is not trading, why".

  M3_PLAN §0.8 asks for this specifically, and gives the reason: the served checkpoint has
  produced **no gated signal since 2026-06-29**. That is correct behaviour — the edge lives
  in volatile bars and the market has been the calmest of the whole 253-day period since
  July — but *a system that has been silent for two months is indistinguishable from a
  broken one*. Reporting bars seen alongside time since the last gated signal, the coverage
  threshold currently in force, and the named reasons the policy skipped bars, makes correct
  silence visible as correct.

  The A/B block is the live counterpart of `docs/M3_2_RESULTS.md`: `policy` against
  `flat_size`, both paper, both charged M3-4's measured per-pair crossing cost. The two take
  the same entries and differ only in size, so the block measures the regime ladder.
  """

  alias FluxTrader.Trading.{ExecCost, Ledger, Policy, Regime, RiskManager}

  def index(conn, _params) do
    json(conn, %{
      ok: true,
      now: DateTime.utc_now(),
      mode: safe(fn -> FluxTrader.Trading.Executor.mode() end, "unknown"),
      # Where a real order would go, and whether one can. `auto_refused` non-nil means the
      # operator asked for auto and the executor fell back to simulation.
      executor: safe(fn -> FluxTrader.Trading.Executor.status() end, %{error: "executor unavailable"}),
      # The exchange's own view of our positions, and any disagreement with the ledger.
      user_stream: safe(fn -> FluxTrader.Binance.UserStream.status() end, %{status: :unavailable}),
      inference: inference_block(),
      signal_liveness: safe(fn -> Ledger.liveness() end, %{error: "database unavailable"}),
      policy: policy_block(),
      regime: safe(fn -> Regime.status() end, %{error: "regime unavailable"}),
      risk: safe(fn -> RiskManager.get_stats() end, %{error: "risk manager unavailable"}),
      ab: safe(fn -> Ledger.ab_summary() end, %{error: "database unavailable"}),
      exec_cost: %{
        # The numbers every paper trade is charged, and where they came from: M3-4's
        # measured per-pair round trip, plus the fee-tier correction found 2026-09-10.
        source: "M3_4_RESULTS.md §1 (measured, $10k order) + fee-tier correction",
        pooled_round_trip_bps: ExecCost.pooled_bps(),
        measured_pooled_round_trip_bps: ExecCost.measured_pooled_bps(),
        superseded_assumption_bps: 14.0,
        measured_fee_bps_per_side: ExecCost.measured_fee_bps_per_side(),
        taker_fee_bps_per_side: ExecCost.taker_fee_bps_per_side(),
        maker_fee_bps_per_side: ExecCost.maker_fee_bps_per_side(),
        fee_correction_bps: ExecCost.fee_correction_bps(),
        fee_tier_verified: true,
        fee_tier_verified_on: ExecCost.fee_verified_on(),
        # What an exchange-filled row is charged instead: two taker fees, no slippage term.
        exchange_fill_round_trip_bps: ExecCost.fee_only_round_trip_bps(),
        measured_pairs: ExecCost.measured_pairs(),
        # Two depths of evidence behind the same table, reported rather than averaged away.
        long_window_pairs: ExecCost.long_window_pairs(),
        short_window_pairs: ExecCost.short_window_pairs(),
        long_window_days: 23,
        short_window_days: 14
      }
    })
  end

  defp policy_block do
    base = %{
      rule: "cov0.02_hold240_rqnone_mcnone_SIZED",
      # The constants are seed 2's, re-derived on REPAIRED candles (eval run 20260904T051921Z)
      # under M3_PROTOCOL §8.3 C4 — see the provenance block on `Policy`. The pre-repair
      # derivation this used to cite is superseded; the numbers it published are not the ones
      # being served. Corrected 2026-09-09.
      source: "docs/M3_2_RESULTS_REPAIRED.md §D1 (repaired eval 20260904T051921Z)",
      coverage: Policy.coverage(),
      hold_minutes: Policy.hold_minutes(),
      signal_horizon_m: Policy.signal_horizon_m(),
      # Reported next to `served_pairs` because the two are different settings and reading
      # one as the other has already cost a production defect (2026-08-28). `served_pairs`
      # is what the policy ranks and trades; this is what the collector subscribes to, and
      # it is allowed to be wider. `inference.pairs` elsewhere in this payload is a third
      # thing again: how many pairs the model returned a signal for on the last run.
      collector_pairs: safe(fn -> Enum.sort(FluxTrader.Settings.get_whitelist()) end, [])
    }

    Map.merge(base, safe(fn -> FluxTrader.Trading.PolicyEngine.status() end, %{ok: false}))
  end

  defp inference_block do
    safe(
      fn ->
        latest = FluxTrader.ML.SignalEngine.latest()

        %{
          ok: latest.inference_ok,
          last_error: latest.last_error,
          last_run_at: latest.last_run_at,
          pairs: map_size(latest.signals)
        }
      end,
      %{ok: false, last_error: "signal engine unavailable"}
    )
  end

  # /health must answer even when a dependency is down — that is the whole point of it.
  defp safe(fun, fallback) do
    fun.()
  rescue
    e -> Map.put(%{error: Exception.message(e)}, :fallback, fallback)
  catch
    :exit, _ -> fallback
  end
end
