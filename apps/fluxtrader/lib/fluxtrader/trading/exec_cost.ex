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

  ## All twelve served pairs carry their own measurement

  M3-4's run measured twelve pairs, not eight. Under the protocol the four added on
  2026-08-14 were reported as "texture only" and excluded from Q1's verdict, because
  pooling 14 days of ladder with 23 into a single decision quantity is what
  M3_4_PROTOCOL §1.5 forbids. **That exclusion governs the verdict, not the charging.**
  A per-pair cost used to charge a trade is not a decision quantity, and using the pair's
  own 14-day number is strictly better than charging it a constant pooled from eight
  *other* pairs.

  ADAUSDT is the case that makes this concrete: it measures **13.733** bps against the
  pooled 9.842, so serving it on the fallback would have understated its cost by 3.89 bps
  — about 40%. Its spread alone (4.901 bps) is 1.7x the widest of the original eight.

  ## Two caveats that belong on every number this module returns

    1. **Regime.** The 23-day measurement window is the calmest month of the evaluation
       period and holds *none* of the policy's trades — the M3-2 winner's last entry
       anywhere is 2026-07-16. Cost rises with volatility (9.77 bps in the calmest BTC-vol
       quintile against 10.09 in the most violent) and this policy only fires in volatile
       bars, so treat the per-pair figures as the optimistic end.
    2. **Fee tier — VERIFIED 2026-09-10, and the assumption was wrong.** M3-4 decomposed
       its measurement into a taker fee of **4.0** bps per side plus slippage. `mix
       flux.fee_tier` read the account's real rate on 2026-09-10: **taker 5.0 / maker 2.0
       bps per side** (the actual USDⓈ-M VIP-0 schedule; 4.0 is the BNB-discounted rate
       nobody had enabled). So every measured number below is **2.0 bps per round trip too
       low**, and `round_trip_bps/1` adds that correction on the way out. The table itself
       is left as measured, so it still matches `docs/M3_4_RESULTS.md` §1 line for line;
       the correction is one constant in one place. Re-run the task after any fee-tier
       change; it compares against the *corrected* fee now.
    3. **Window depth.** XRP, LINK, AVAX and ADA rest on 14 days and ~3,960 observations
       against the others' 23 days and ~6,400. `round_trip_bps/1` tags them
       `:measured_short_window` so the difference is visible at the call site rather than
       buried here.
  """

  # Per-pair measured crossing cost, round trip, bps — M3_4_RESULTS.md §1 (`C_taker`).
  #
  # The first eight rest on 23 days of ladder; the last four on 14 (they were added to the
  # collector on 2026-08-14). Both blocks come from the same run of the same study, and the
  # split is recorded in `@short_window` rather than by keeping two maps, so there is exactly
  # one place a number lives.
  @measured %{
    "BTCUSDT" => 8.017,
    "ETHUSDT" => 8.057,
    "HYPEUSDT" => 9.125,
    "SOLUSDT" => 9.242,
    "ZECUSDT" => 9.448,
    "DOGEUSDT" => 9.538,
    "1000PEPEUSDT" => 11.263,
    "WLDUSDT" => 14.060,
    "XRPUSDT" => 9.075,
    "LINKUSDT" => 10.754,
    "AVAXUSDT" => 11.401,
    "ADAUSDT" => 13.733
  }

  # The four measured on the shorter ladder. They are charged exactly like the other eight —
  # a cost is a cost — but `round_trip_bps/1` tags them so a caller that cares about the
  # depth of the evidence can see it, and so `/api/health` can report the split.
  @short_window MapSet.new(["XRPUSDT", "LINKUSDT", "AVAXUSDT", "ADAUSDT"])

  # Pooled over the eight LONG-WINDOW pairs, day-clustered (M3_4_RESULTS.md §2, Q1). It is
  # deliberately NOT re-pooled over twelve: Q1 is a pre-registered decision quantity measured
  # on 23 days, and re-pooling it across two depths of evidence is what M3_4_PROTOCOL §1.5
  # forbids. Since every served pair now carries its own measurement, nothing the policy
  # trades is charged this number any more — it survives as the fallback for a pair that has
  # never been measured at all.
  @pooled 9.842

  # The taker fee per side M3-4's measurement decomposes to (M3_4_PROTOCOL §2.6). It is
  # what `@measured` and `@pooled` were computed with, and it is NOT what the account pays.
  @measured_fee_bps_per_side 4.0

  # What the account actually pays, read off `/fapi/v1/commissionRate` on 2026-09-10 by
  # `mix flux.fee_tier` (BTCUSDT: taker 0.000500, maker 0.000200). The fee is account-level
  # on USDⓈ-M, not per symbol.
  @verified_taker_fee_bps_per_side 5.0
  @verified_maker_fee_bps_per_side 2.0
  @fee_verified_on ~D[2026-09-10]

  # Round-trip correction applied to every measured cost: two sides of (verified - measured).
  @fee_correction_bps 2.0 * (@verified_taker_fee_bps_per_side - @measured_fee_bps_per_side)

  @doc "Every pair M3-4 measured a crossing cost for — all twelve served pairs."
  def measured_pairs, do: Map.keys(@measured) |> Enum.sort()

  @doc "The eight measured on 23 days of ladder."
  def long_window_pairs,
    do: Map.keys(@measured) |> Enum.reject(&MapSet.member?(@short_window, &1)) |> Enum.sort()

  @doc "The four measured on 14 days of ladder (collected from 2026-08-14)."
  def short_window_pairs, do: MapSet.to_list(@short_window) |> Enum.sort()

  @doc """
  Round-trip crossing cost for `pair`, in bps.

  Returns `{provenance, bps}`:

    * `:measured` — 23 days of ladder;
    * `:measured_short_window` — 14 days, the four pairs added 2026-08-14;
    * `:pooled_fallback` — no measurement at all, charged the pooled 9.842 and flagged.

  The fallback is flagged rather than silent because charging BTC's 8.0 bps on a pair whose
  spread was never measured is the kind of default that makes a backtest look better than the
  market. ADAUSDT is the standing example of why: it measures **13.733** bps, 3.89 above the
  pooled number it would otherwise have been charged.
  """
  def round_trip_bps(pair) when is_binary(pair) do
    {tag, bps} = measured_round_trip_bps(pair)
    {tag, Float.round(bps + @fee_correction_bps, 3)}
  end

  @doc """
  The round trip exactly as M3-4 measured it, at the 4.0 bps fee the study assumed — i.e.
  `round_trip_bps/1` **without** the fee-tier correction. For comparing against
  `docs/M3_4_RESULTS.md` §1; never for charging a trade.
  """
  def measured_round_trip_bps(pair) when is_binary(pair) do
    up = String.upcase(pair)

    case Map.fetch(@measured, up) do
      {:ok, bps} ->
        if MapSet.member?(@short_window, up), do: {:measured_short_window, bps}, else: {:measured, bps}

      :error ->
        {:pooled_fallback, @pooled}
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

  @doc "Pooled round-trip crossing cost over the eight long-window pairs, bps, fee-corrected."
  def pooled_bps, do: Float.round(@pooled + @fee_correction_bps, 3)

  @doc "The pooled cost as M3-4 published it, before the fee-tier correction."
  def measured_pooled_bps, do: @pooled

  @doc "The taker fee per side M3-4's measurement assumed, bps."
  def measured_fee_bps_per_side, do: @measured_fee_bps_per_side

  @doc "The taker fee per side the account pays, bps — verified by `mix flux.fee_tier`."
  def taker_fee_bps_per_side, do: @verified_taker_fee_bps_per_side

  @doc "The maker fee per side the account pays, bps. Informational: nothing here rests."
  def maker_fee_bps_per_side, do: @verified_maker_fee_bps_per_side

  @doc "When the fee tier was last read off the account."
  def fee_verified_on, do: @fee_verified_on

  @doc "What the correction adds to every measured round trip, bps."
  def fee_correction_bps, do: @fee_correction_bps

  @doc """
  The cost charged to a row whose entry and exit are REAL fills: the two taker fees and
  nothing else. Slippage is already inside an exchange fill price, so charging the measured
  round trip on top of it would count the slippage twice.
  """
  def fee_only_round_trip_bps, do: 2.0 * @verified_taker_fee_bps_per_side

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
