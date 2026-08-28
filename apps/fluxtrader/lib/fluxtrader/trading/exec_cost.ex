defmodule FluxTrader.Trading.ExecCost do
  @moduledoc """
  What it costs us to get in and out of a position, in basis points.

  A **basis point (bps)** is one hundredth of one percent. A **round trip** is the whole
  cost of one trade, entry and exit together. **Crossing** (taker) means hitting the resting
  quote for an instant fill; **resting** (maker) means posting a limit order and waiting.

  ## Why these numbers, and why there is no maker path here

  M3-4 (`docs/M3_4_RESULTS.md`, 2026-08-28) measured both arms on 23 days of order-book
  history at a $10,000 order size and found two things:

    * Crossing costs **9.84 bps round trip pooled**, not the 14 bps every published M3
      number assumed. The 95% interval excludes 14, so the old assumption was mis-stated in
      the pessimistic direction.
    * Resting looks 3.60 bps cheaper on the fee arithmetic alone, but the adverse-selection
      panel is negative in **16 of 16** (pair, direction) cells: a resting buy fills because
      the price came down through it and then keeps going. The saving is a fee-rebate
      accounting gain, not a trading gain.

  So the executor crosses, always, and this module carries no queue model, no fill
  probability and no maker branch. That is a decision M3-4 paid for; see M3_PLAN §0.8.

  ## Two caveats that belong on every number this module returns

    1. **Regime.** The 23-day measurement window is the calmest month of the evaluation
       period and holds *none* of the policy's trades — the M3-2 winner's last entry
       anywhere is 2026-07-16. Cost rises with volatility (9.77 bps in the calmest BTC-vol
       quintile against 10.09 in the most violent) and this policy only fires in volatile
       bars, so treat the per-pair figures as the optimistic end.
    2. **Fee tier.** The measurement decomposes into a taker fee of 4.0 bps per side plus
       slippage. That fee is the published Binance USDⓈ-M VIP-0 rate, **not** a figure read
       off this account. `mix flux.fee_tier` checks it; a different tier shifts every number
       here by a constant. M3_4_PROTOCOL §2.5 makes that check a precondition of M3-5.
  """

  # Per-pair measured crossing cost, round trip, bps — M3_4_RESULTS.md §1 (`C_taker`).
  @measured %{
    "BTCUSDT" => 8.017,
    "ETHUSDT" => 8.057,
    "HYPEUSDT" => 9.125,
    "SOLUSDT" => 9.242,
    "ZECUSDT" => 9.448,
    "DOGEUSDT" => 9.538,
    "1000PEPEUSDT" => 11.263,
    "WLDUSDT" => 14.060
  }

  # Pooled over the eight served pairs, day-clustered (M3_4_RESULTS.md §2, Q1).
  @pooled 9.842

  # The taker fee per side the measurement decomposes to. Published VIP-0; unverified
  # against the account until `mix flux.fee_tier` says otherwise.
  @assumed_taker_fee_bps_per_side 4.0

  @doc "The eight pairs M3-4 measured, which are also the eight served pairs (T6)."
  def measured_pairs, do: Map.keys(@measured) |> Enum.sort()

  @doc """
  Round-trip crossing cost for `pair`, in bps.

  An unmeasured pair falls back to the pooled 9.842 and is flagged, because silently
  charging BTC's 8.0 bps on a pair whose spread was never measured is the kind of default
  that makes a backtest look better than the market.
  """
  def round_trip_bps(pair) when is_binary(pair) do
    case Map.fetch(@measured, String.upcase(pair)) do
      {:ok, bps} -> {:measured, bps}
      :error -> {:pooled_fallback, @pooled}
    end
  end

  @doc "Round-trip cost as a plain float, dropping the provenance tag."
  def cost_bps(pair), do: round_trip_bps(pair) |> elem(1)

  @doc """
  Cost charged at one side of the trade, in bps — half the round trip.

  Splitting it evenly is a modelling choice, not a measurement: M3-4 measured the round
  trip as a single quantity. It matters only for how an open position is marked, never for
  the realised P&L of a closed one.
  """
  def side_bps(pair), do: cost_bps(pair) / 2.0

  @doc "Pooled round-trip crossing cost over the eight served pairs, bps."
  def pooled_bps, do: @pooled

  @doc "The taker fee per side the measurement assumes, bps. Unverified against the account."
  def assumed_taker_fee_bps_per_side, do: @assumed_taker_fee_bps_per_side

  @doc """
  Net return of a closed trade, in bps.

  `signed_gross_ret` is `side * fwd_ret * size` in return units (0.001 = 10 bps), exactly
  as `ml/train/m3/backtest.py` books it. The cost is charged **once per unit of size**, not
  per unit of notional: a 5/3-size trade crosses 5/3 as much notional and pays 5/3 as much.
  """
  def net_bps(pair, signed_gross_ret, size \\ 1.0) do
    signed_gross_ret * 1.0e4 - cost_bps(pair) * size
  end
end
