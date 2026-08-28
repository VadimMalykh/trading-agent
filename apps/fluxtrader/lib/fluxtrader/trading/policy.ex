defmodule FluxTrader.Trading.Policy do
  @moduledoc """
  The M3 policy: **`cov0.02_hold240_rqnone_mcnone_SIZED`**, and nothing else.

  This module is pure. It holds no state, touches no database and places no orders — it
  answers one question, "given this bar, should we be entering, on which side, how large",
  so that the rule exists in exactly one place and can be tested against the backtest that
  chose it (`ml/train/m3/backtest.py`).

  ## The rule, in plain language

  Every five minutes each pair produces a **confidence** — how sure the M2 model is about
  direction. We enter on the **top 2% of bars by confidence**, take the model's side, hold
  for **four hours**, and then close. Size is scaled between **one third and five thirds**
  of the base by how violent the market has been: the quieter the last 24 hours of Bitcoin,
  the smaller we go. There is no stop, no take-profit and no cap on how many pairs can be
  open at once; there is one position per pair at a time.

  On the 253-day evaluation period this earned **+15.0 bps per trade** net of the 14-bps
  cost assumed at the time, at about **2.3 trades a day**, and it is the one configuration
  of the 36 searched that cleared every pre-registered Tier-1 criterion
  (`docs/M3_2_RESULTS.md`). M3-4 later measured the true crossing cost at 9.84 bps, so the
  real figure is better than that, not worse.

  ## The three invariants, which are findings and not preferences

    1. **Entry is by coverage rank, never by a confidence constant.** The same probability
       is 1.2% / 2.5% / 1.7% coverage across the three trained seeds, so `conf > 0.63` means
       something different on every checkpoint. `coverage_threshold/2` derives the cut from
       a population of bars.
    2. **Positions are serial per pair.** While a position is open on a pair, new signals on
       that pair are ignored. Overlapping 4h entries book the same move several times.
    3. **Sizing buckets against the distribution of BARS, not of trades.** The regime cut has
       to be a statement about the market, derivable without knowing which bars the model
       gated. A quantile taken over already-selected trades is conditioned on the model.

  ## What differs live, and why

  The backtest derives its coverage threshold from the whole evaluation split, which is
  lookahead it can afford because it is scoring, not trading. Live, the threshold comes from
  a **trailing window of bars already seen**. That is strictly more conservative, and it is
  also the behaviour §1.3.3 actually wants: it holds coverage at 2% while the model's
  confidence scale drifts, instead of freezing a number that silently changes meaning.

  Everything else — tie handling, the bucket edges, the size ladder, the hold — is the same
  arithmetic as `backtest.py`, and `test/fluxtrader/trading/policy_test.exs` pins it to the
  values that file produces.
  """

  @coverage 0.02
  @hold_minutes 240
  @signal_horizon_m 240
  @bar_seconds 300
  @size_buckets 5

  defstruct coverage: @coverage,
            hold_minutes: @hold_minutes,
            signal_horizon_m: @signal_horizon_m,
            size_by_regime: true,
            max_concurrent: nil

  @type t :: %__MODULE__{}

  @doc """
  The policy as M3-2 selected it. Take this and change nothing without a new protocol —
  M3_PROTOCOL §0 forbids re-tuning against the same evidence.
  """
  def spec, do: %__MODULE__{}

  def coverage, do: @coverage
  def hold_minutes, do: @hold_minutes
  def signal_horizon_m, do: @signal_horizon_m
  def bar_seconds, do: @bar_seconds

  @doc """
  Floor a timestamp onto the 5-minute bar grid the model is scored on.

  The signal engine polls every 30 seconds; the policy decides once per bar. Without this
  the same bar would be counted ten times in the confidence distribution and the 2% cut
  would be taken over a population that is mostly duplicates.
  """
  def bar_ts(%DateTime{} = ts) do
    secs = DateTime.to_unix(ts)
    DateTime.from_unix!(secs - Integer.mod(secs, @bar_seconds))
  end

  @doc """
  The confidence cut for a coverage fraction: the k-th largest value, `k = round(n * c)`.

  Selection is then `conf >= threshold`, which is **tie-inclusive**. `backtest.py` documents
  why: `torch.topk` resolves boundary ties in an order that is an artifact of its kernel and
  is not reproducible, so "every bar at or above the k-th largest" is the only definition of
  "the top c% of bars" that is deterministic and re-derivable.

  Returns `{:error, :empty}` rather than a number when the population selects no bars, so a
  caller can never mistake a cold start for a threshold of zero.
  """
  def coverage_threshold([], _coverage), do: {:error, :empty}

  def coverage_threshold(confidences, coverage) when is_list(confidences) do
    n = length(confidences)
    k = round(n * coverage)

    if k <= 0 do
      {:error, :empty}
    else
      k = min(k, n)
      # The k-th largest. Sorting is fine at these sizes: a 14-day window over 8 pairs is
      # ~32k floats and this runs once every five minutes.
      {:ok, confidences |> Enum.sort(:desc) |> Enum.at(k - 1)}
    end
  end

  @doc """
  Quintile edges of a regime population — the four cuts at 20/40/60/80%.

  Uses linear interpolation between order statistics, matching pandas' default
  `quantile()`, which is what `backtest.py` calls to build these edges.
  """
  def quintile_edges([]), do: {:error, :empty}

  def quintile_edges(values) when is_list(values) do
    sorted = Enum.sort(values)
    {:ok, Enum.map([0.2, 0.4, 0.6, 0.8], &interpolated_quantile(sorted, &1))}
  end

  defp interpolated_quantile(sorted, q) do
    n = length(sorted)
    pos = (n - 1) * q
    lo = trunc(pos)
    hi = min(lo + 1, n - 1)
    frac = pos - lo
    Enum.at(sorted, lo) * (1.0 - frac) + Enum.at(sorted, hi) * frac
  end

  @doc """
  Size multiplier for a regime value against bar-quintile `edges`: 1/3, 2/3, 1, 4/3, 5/3.

  `bucket = searchsorted(edges, value, side="right")`, so a value exactly on an edge falls
  into the bucket *above* it — the same tie convention numpy uses in `backtest.py`.

  Trading small out of regime rather than not at all is what makes this the SIZED variant.
  It is the soft form of the hard regime filter, and it is the form that survived scoring:
  every configuration using the hard filter failed Tier 1.
  """
  def size_multiplier(value, edges) when is_number(value) and is_list(edges) do
    bucket = Enum.count(edges, fn e -> value >= e end)
    (bucket + 1) / 3.0
  end

  @doc "How many size buckets the ladder has. Present so tests cannot drift from the ladder."
  def size_buckets, do: @size_buckets

  @doc """
  Decide what to do with one bar.

  `bar` carries the model's output for this (pair, bar): `:pair`, `:confidence`, `:side`
  (`+1` up / `-1` down / `0` flat), `:price` and `:ts`.

  `ctx` carries everything the rule needs that is not in the bar:

    * `:threshold` — the coverage cut from `coverage_threshold/2`, or `nil` while cold
    * `:regime_edges` — quintile edges of `btc_absret_1d`, or `nil` while cold
    * `:regime` — the current `btc_absret_1d`, or `nil` if unavailable
    * `:open_pairs` — a MapSet of pairs already holding a position (invariant 2)
    * `:open_count` — how many positions are open across all pairs

  Returns `{:enter, decision}` or `{:skip, reason}`. Every skip names its reason, because
  "the system placed no trades today" and "the system is broken" have to be distinguishable
  from the outside — a live policy that has been correctly silent since June looks exactly
  like a dead one otherwise.
  """
  def decide(spec \\ spec(), bar, ctx)

  def decide(%__MODULE__{} = spec, bar, ctx) do
    cond do
      is_nil(ctx[:threshold]) ->
        {:skip, :warming_up}

      bar.side == 0 ->
        {:skip, :no_side}

      bar.confidence < ctx.threshold ->
        {:skip, :below_coverage}

      MapSet.member?(ctx[:open_pairs] || MapSet.new(), bar.pair) ->
        {:skip, :position_open}

      spec.max_concurrent != nil and (ctx[:open_count] || 0) >= spec.max_concurrent ->
        {:skip, :max_concurrent}

      spec.size_by_regime and (is_nil(ctx[:regime]) or is_nil(ctx[:regime_edges])) ->
        # Dropping the bar rather than defaulting to size 1.0. `backtest.py` drops bars
        # whose regime lookback is incomplete for the same reason: a missing observable is
        # not a neutral one.
        {:skip, :no_regime}

      true ->
        size =
          if spec.size_by_regime,
            do: size_multiplier(ctx.regime, ctx.regime_edges),
            else: 1.0

        {:enter,
         %{
           pair: bar.pair,
           side: bar.side,
           size: size,
           confidence: bar.confidence,
           threshold: ctx.threshold,
           regime: ctx[:regime],
           entry_price: bar.price,
           entry_ts: bar.ts,
           exit_after_ts: DateTime.add(bar.ts, spec.hold_minutes * 60, :second)
         }}
    end
  end

  @doc """
  The signal-only control arm: enter on every bar M2's own gate approves, flat size.

  This is the A/B's other side (M3_PLAN §2 M3-5 item 4). It shares the hold, the serial-per-
  pair rule and the measured crossing cost with the policy arm, so the only thing that
  differs between the two ledgers is **coverage selection and sizing** — which is exactly
  what the policy claims to add.
  """
  def decide_signal_only(%__MODULE__{} = spec \\ spec(), bar, ctx) do
    cond do
      not bar.gated ->
        {:skip, :not_gated}

      bar.side == 0 ->
        {:skip, :no_side}

      MapSet.member?(ctx[:open_pairs] || MapSet.new(), bar.pair) ->
        {:skip, :position_open}

      true ->
        {:enter,
         %{
           pair: bar.pair,
           side: bar.side,
           size: 1.0,
           confidence: bar.confidence,
           threshold: nil,
           regime: ctx[:regime],
           entry_price: bar.price,
           entry_ts: bar.ts,
           exit_after_ts: DateTime.add(bar.ts, spec.hold_minutes * 60, :second)
         }}
    end
  end
end
