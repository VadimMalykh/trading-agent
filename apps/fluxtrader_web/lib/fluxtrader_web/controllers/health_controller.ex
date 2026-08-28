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
  `signal_only`, both paper, both charged M3-4's measured per-pair crossing cost.
  """

  alias FluxTrader.Trading.{ExecCost, Ledger, Policy, Regime, RiskManager}

  def index(conn, _params) do
    json(conn, %{
      ok: true,
      now: DateTime.utc_now(),
      mode: safe(fn -> FluxTrader.Trading.Executor.mode() end, "unknown"),
      inference: inference_block(),
      signal_liveness: safe(fn -> Ledger.liveness() end, %{error: "database unavailable"}),
      policy: policy_block(),
      regime: safe(fn -> Regime.status() end, %{error: "regime unavailable"}),
      risk: safe(fn -> RiskManager.get_stats() end, %{error: "risk manager unavailable"}),
      ab: safe(fn -> Ledger.ab_summary() end, %{error: "database unavailable"}),
      exec_cost: %{
        # The numbers every paper trade is charged, and where they came from.
        source: "M3_4_RESULTS.md §1 (measured, 23 days of book history, $10k order)",
        pooled_round_trip_bps: ExecCost.pooled_bps(),
        superseded_assumption_bps: 14.0,
        assumed_taker_fee_bps_per_side: ExecCost.assumed_taker_fee_bps_per_side(),
        fee_tier_verified: false,
        measured_pairs: ExecCost.measured_pairs()
      }
    })
  end

  defp policy_block do
    base = %{
      rule: "cov0.02_hold240_rqnone_mcnone_SIZED",
      source: "docs/M3_2_RESULTS.md §D1",
      coverage: Policy.coverage(),
      hold_minutes: Policy.hold_minutes(),
      signal_horizon_m: Policy.signal_horizon_m()
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
