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

    1. **Entry is by coverage rank taken over the SCORING population, and that rank is then
       frozen to a number.** The same probability is 1.2% / 2.5% / 1.7% coverage across the
       three trained seeds, so `conf > 0.63` means something different on every checkpoint —
       which is why the cut is *derived* by `coverage_threshold/2` rather than guessed. But
       it is derived **once, offline, on the checkpoint and universe being served**, and the
       resulting constant is what runs. Re-deriving it live against a trailing window is a
       different rule; §"What differs live" says what that cost.
    2. **Positions are serial per pair.** While a position is open on a pair, new signals on
       that pair are ignored. Overlapping 4h entries book the same move several times.
    3. **Sizing buckets against the distribution of BARS, not of trades.** The regime cut has
       to be a statement about the market, derivable without knowing which bars the model
       gated. A quantile taken over already-selected trades is conditioned on the model.

  ## What differs live, and why — the 2026-08-31 freeze

  🔴 **Nothing differs any more, and that is the point of this section.** Until 2026-08-31 it
  did, in two places, and both were wrong:

    * the coverage cut was re-derived live as the top 2% of a **trailing 14 days** of recorded
      bars (now `Ledger.rolling_coverage_threshold/3`); and
    * the sizing ladder's quintile edges were re-derived live over a **trailing 30 days** of
      BTC klines (`Regime`).

  The reasoning written here before the measurement was that a trailing rank is "strictly more
  conservative". **It is not, and `m3 fidelity` measured it.** A trailing rank admits 2% of
  bars in *every* window **by construction** — including a window the fixed cut would have sat
  out completely. It is regime-adaptive in the wrong direction: it lowers the bar precisely
  when the model has nothing to say, which is exactly where the edge is known to be absent
  (NEXT_TRAINING_PLAN §1.8 — the edge lives in volatile bars).

  On the served checkpoint's own family — the three banked seeds M3-2 chose on — the rolling
  cut sat below the fixed one on **66% / 72% / 69%** of warm bars, took **2,316 trades against
  1,773**, and **56% of them were on bars the fixed cut rejects**. Net taker bps went
  **+15.03 → +8.62**, and the number M3-1 actually scores on, the worst window, went
  **+0.25 → −8.88**: the served rule fails the criterion the policy was selected against. On
  the wider O8 population the same substitution changes the edge's *sign*, +21.44 → −18.43.
  The ladder is the same class of defect and costs about 1.5 bps alone, so it was frozen in
  the same change rather than left for a second clock reset. Full result:
  `docs/M3_FIDELITY_RESULTS.md`.

  So both quantities are now **constants, derived offline on the served checkpoint's own
  evaluation split**, and `decide/3` runs the arithmetic `backtest.py` runs. Everything else —
  tie handling, the bucket convention, the 1/3..5/3 ladder, the hold — was already identical,
  and `test/fluxtrader/trading/policy_test.exs` pins all of it to the values that file
  produces.

  ⚠️ **The freeze has a consequence, and it is intended: the policy goes silent when the
  market is calm.** August 2026's confidence never exceeded 0.569 against a cut of 0.6319, so
  the validated rule would have taken **zero** trades all month. That is correct silence, not
  a fault, and it is what `/api/health` was built to make visible.

  🔴 **The constants belong to a CHECKPOINT.** A confidence cut is a statement about one
  model's confidence scale and does not transfer to another — see `frozen_threshold/0`, which
  records what happened when this freeze first tried to take the cut from a different run.
  Promoting a new checkpoint invalidates both.
  """

  @coverage 0.02
  @hold_minutes 240
  @signal_horizon_m 240
  @bar_seconds 300
  @size_buckets 5

  # ---------------------------------------------------------------- the frozen constants
  #
  # Both are derived offline by `backtest.py` over the WHOLE evaluation split of the served
  # run, which is the population M3-2's numbers are measured on. They are restated here as
  # literals because there is no import across the two runtimes;
  # `test/fluxtrader/trading/config_test.exs` is where this side asserts its copies, and a
  # change on either side has to be made on both.
  #
  # Provenance — **seed 2, run 20260819T142759Z**: the SERVED checkpoint
  # (`m2_multi_20260819T142759Z_a186182b.pt`). 579,539 bars in the 240m head over the eight
  # pairs it was evaluated on. Re-derive with:
  #
  #     ./scripts/m3.sh -m m3 fidelity --universe 8
  #
  # whose arm A is this rule. Recomputing the two lines below reproduces seed 2's arm A
  # exactly: 483 trades, mean size 1.362, entry confidence 0.6320 .. 0.7820.
  #
  # 🔴 THE CUT BELONGS TO A CHECKPOINT, NOT JUST TO A UNIVERSE. A first attempt at this
  # freeze took the cut from O8 (run 20260822T012619Z), because O8 is the only run evaluated
  # over all twelve served pairs. O8 is a DIFFERENT TRAINED MODEL, and NEXT_TRAINING_PLAN
  # §1.5 closed absolute-threshold-across-checkpoints as "not a lever, a defect": the same
  # probability is 1.2% / 2.5% / 1.7% coverage across three seeds of one configuration.
  # Measured here: **O8's 0.5992 applied to seed 2's bars realizes 4.01% coverage**, double
  # the 0.02 M3-2 searched. Serving another model's cut would have doubled the trade rate —
  # a smaller version of the very defect this freeze exists to fix.
  #
  # ⚠️ KNOWN GAP, deliberate and recorded. These come from seed 2's **8-pair** split, and
  # twelve pairs are served. A fixed threshold stays well-defined on a wider universe — it is
  # a statement about this model's confidence scale, which does not change when pairs are
  # added — but the *realized coverage* will not be exactly 2%. Closing that properly needs
  # seed 2 re-evaluated over twelve pairs, for which no dump exists, and doing so would also
  # settle the parked "coverage at twelve pairs" pre-registration (T6's count-matched cut is
  # 0.01288) as a side effect. M3_PROTOCOL §0 says that question needs its own
  # pre-registration, so it is left open rather than answered by accident.

  # `coverage_threshold(conf, 0.02)` over the split — the k-th largest confidence,
  # k = round(n * 0.02). Selection is `conf >= threshold`, tie-inclusive.
  @frozen_threshold 0.6318973898887634

  # `r["btc_absret_1d"].quantile([0.2, 0.4, 0.6, 0.8])` over BARS, not over trades — the
  # ladder has to be a statement about the market (invariant 3).
  #
  # 🟢 Unlike the cut, this one is near-transferable, and the reason is worth stating: it is a
  # quantile of BITCOIN'S trailing 24-hour move, which is a fact about the market rather than
  # about a checkpoint — O8's split puts the same four edges within 2% of these. It is still
  # taken from the served checkpoint's own split, because there is no reason to mix sources.
  #
  # ⚠️ The p80 here is 0.0252, NOT the 0.0431 NEXT_TRAINING_PLAN §1.8 published. Both are
  # correct: §1.8 measured on an earlier window. The health endpoint compares the live
  # trailing p80 against THIS number, because this is the ladder in force.
  @frozen_regime_edges [
                         0.00391214806586504,
                         0.008861115202307701,
                         0.015078878961503506,
                         0.025166796520352364
                       ]

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
  The confidence cut in force: **the constant `backtest.py` derived on the served run**.

  🔴 **This belongs to a CHECKPOINT.** It is the top-2% cut of the served checkpoint's own
  evaluation split, and a confidence threshold does not transfer between checkpoints: §1.5
  measured the same probability as 1.2% / 2.5% / 1.7% coverage across three seeds of one
  configuration, and O8's cut applied to this checkpoint realizes 4.01% rather than 2%.
  Promoting a different checkpoint invalidates this number outright — re-derive it first, and
  reset the forward clock, because the A/B would otherwise span two rules.

  ⚠️ Nothing currently *fails* when the checkpoint changes. `served_pairs` is guarded by
  `config_test.exs`; the served weights are not, because the app has no handle on what
  `ml_inference` loaded. That gap is filed in `docs/M3_FIDELITY_RESULTS.md` §6.5.

  Coverage itself stays 0.02. Freezing the cut is **not** re-picking a searched dimension —
  M3_PROTOCOL §0 forbids that — it is making the served code compute the dimension the way
  the scoring code did.
  """
  def frozen_threshold, do: @frozen_threshold

  @doc """
  The sizing ladder's quintile edges in force, from the same split as `frozen_threshold/0`.

  Frozen for the same reason and in the same change: a trailing ladder re-sizes the same
  market state differently from month to month, so `size_multiplier/2` would not be the
  function that was scored. It costs less than the cut did (~1.5 bps, arm C of the fidelity
  replay) but a separate fix would have cost a second clock reset.
  """
  def frozen_regime_edges, do: @frozen_regime_edges

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

  ⚠️ **This is the derivation, not the cut in force.** Since the 2026-08-31 freeze the served
  cut is `frozen_threshold/0`, produced by running exactly this arithmetic offline over the
  whole evaluation split. This function survives because that is where the constant comes
  from, and because `Ledger.rolling_coverage_threshold/3` still computes a trailing one as a
  **drift diagnostic** on `/api/health`. Nothing routes a value from either into `decide/3`.
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

  ⚠️ Same standing as `coverage_threshold/2`: this is how `frozen_regime_edges/0` was
  produced, and `Regime` still runs it over a trailing 30 days as a drift diagnostic, but the
  ladder in force is the frozen one.
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

    * `:threshold` — the coverage cut. Since the freeze the engine always passes
      `frozen_threshold/0`, so the `:warming_up` branch below is unreachable in production;
      it is kept because the function is pure and a test may drive it with `nil`.
    * `:regime_edges` — the ladder, likewise always `frozen_regime_edges/0` live
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
  The control arm: **the same bars as the policy, at flat size 1.0.**

  ## Why this is `decide/3` and not a second rule

  It delegates. Every entry condition — the frozen cut, the side, serial-per-pair, the regime
  being present — is whatever `decide/3` says it is, and the only thing this function changes
  is the size. That is deliberate and is the entire point of the arm: **the two ledgers then
  differ in exactly one dimension**, so any difference between them is attributable to the
  1/3..5/3 regime ladder and to nothing else. Two independently written entry rules could
  drift apart under a later edit and quietly turn the comparison into a two-variable one.

  Note it keeps the `:no_regime` skip even though a flat size does not need a regime value.
  That looks redundant and is not: dropping it would let the control enter bars the policy
  refuses, which is precisely the divergence this arm is built to avoid.

  ## What replaced, and why — 2026-08-31

  🔴 This used to be `decide_signal_only/3`: *every bar M2's own serve gate approves*, flat
  size. It was pre-registered in `docs/M3_5_INTEGRATION.md` §4 and it **structurally could not
  produce data.** `bar.gated` requires M2's gate, and no bar had been gated across 8,184 bars
  since 2026-06-29 — the control sat at 0 trades against the policy arm's 12, and would have
  stayed there for as long as the calm lasted, which is open-ended. An A/B with one arm is not
  an A/B.

  The question that arm asked — *what does the M3-2 rule add over M2's raw gated signal?* — is
  already answered offline, and the live version of it was waiting on a gate nobody controls.
  The question this arm asks instead is the one the policy actually claims to answer: **is the
  regime sizing worth anything?** M3-2 says it is worth +8.6 bps on the worst window, which is
  the whole difference between failing Tier 1 and passing it, and that claim has never been
  checked forward.

  ⚠️ This is a **re-registration**, dated and recorded, not a quiet edit — see
  `docs/M3_5_INTEGRATION.md` §4. It was made before any comparable live evidence existed
  (twelve trades, all of which are discarded in the same change), so it cannot be a choice
  made after seeing which control looked better.

  ## The one way the arms can still diverge, and why it is left alone

  The policy arm passes through `RiskManager`; this one never does, because a control that
  could be refused for lack of a slot would flatter the policy by throttling only its
  competitor. So if risk refuses a policy entry, that pair is held here and not there, and the
  two arms' `:position_open` skips fall out of step until both are flat again. That is the
  honest behaviour — the alternative, mirroring executions rather than decisions, reintroduces
  exactly the bias the separation exists to prevent. `risk_rejections` on `/api/health` is
  where a reader sees it happening.
  """
  def decide_flat(spec \\ spec(), bar, ctx)

  def decide_flat(%__MODULE__{} = spec, bar, ctx) do
    case decide(spec, bar, ctx) do
      {:enter, decision} -> {:enter, %{decision | size: 1.0}}
      {:skip, _} = skip -> skip
    end
  end
end
