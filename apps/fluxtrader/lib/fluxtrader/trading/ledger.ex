defmodule FluxTrader.Trading.Ledger do
  @moduledoc """
  Persistence for the policy: the bar log it ranks against, and the paper ledger it writes.

  Two things live here rather than in a GenServer's state, and both for the same reason:
  **a redeploy must not reset the experiment.** The forward paper test exists to manufacture
  independent trading days (M3_PLAN §0.5.4), and an in-memory ledger would silently restart
  that clock every time the container was rebuilt.
  """
  import Ecto.Query

  alias FluxTrader.Repo
  alias FluxTrader.Trading.{ExecCost, PaperTrade, PolicyBar}

  # How far back the coverage rank looks. The backtest ranks over its whole split, which is
  # lookahead it can afford because it is scoring rather than trading; live, the population
  # can only be bars already seen. 14 days over 8 pairs is ~32k bars, which resolves a 2%
  # cut to ~640 bars — enough that the threshold does not jump around from day to day.
  @rank_window_days 14
  # Below this the top-2% cut is a handful of bars and the policy stays cold: 2,016 bars
  # makes the cut 40 bars wide.
  #
  # 🔴 It is a BAR COUNT, not a calendar span, and the `7 * 288` spelling is misleading about
  # how long it takes to clear. The count is pooled across served pairs, so the population
  # grows at (pairs x 288)/day: eight pairs clear it in ~21 hours and twelve in ~14, not in
  # seven days. Every document that described this as "a seven-day wait" was wrong, and the
  # 2026-08-28 deploy was mis-forecast on that basis.
  #
  # ⚠️ OPEN QUESTION, deliberately not changed while widening the universe on 2026-08-29:
  # whether a bar count is the right floor at all. It guarantees the cut is statistically
  # wide enough, but says nothing about the cut being drawn from more than one market
  # regime — at twelve pairs the threshold can be derived from a single 14-hour stretch. A
  # calendar floor alongside the count would fix that, and would make the constant mean what
  # its original spelling claimed. It is a change to the cold-start rule, so it wants its own
  # decision rather than being smuggled in with a universe change.
  @min_rank_bars 7 * 288
  # Bars older than this are dropped. Two rank windows, so there is always a full window
  # available plus room to widen it without losing history.
  @retain_days 60

  def rank_window_days, do: @rank_window_days
  def min_rank_bars, do: @min_rank_bars

  # ---------------------------------------------------------------- the bar log

  @doc """
  Record one (pair, bar) observation. Idempotent: the signal engine polls every 30 seconds
  and the same 5-minute bar arrives ten times, so a repeat is a no-op rather than a
  duplicate row that would distort the ranking population.
  """
  def record_bar(attrs) do
    %PolicyBar{}
    |> PolicyBar.changeset(attrs)
    |> Repo.insert(on_conflict: :nothing, conflict_target: [:pair, :bar_ts, :horizon_m])
  end

  @doc """
  The coverage cut: the k-th largest confidence over the trailing window, `k = round(n*c)`.

  This is the same definition as `Policy.coverage_threshold/2` and is deliberately expressed
  as `ORDER BY confidence DESC OFFSET k-1 LIMIT 1` rather than by pulling the window into
  the VM — the arithmetic is identical, and selection stays `conf >= threshold`, which is
  tie-inclusive.

  Returns `{:error, :cold, n}` while the window holds too few bars to rank against, so a
  cold start is never mistaken for a threshold of zero.
  """
  def coverage_threshold(coverage, horizon_m, now \\ DateTime.utc_now()) do
    since = DateTime.add(now, -@rank_window_days * 86_400, :second)

    n =
      Repo.aggregate(
        from(b in PolicyBar, where: b.bar_ts >= ^since and b.horizon_m == ^horizon_m),
        :count
      )

    k = round(n * coverage)

    cond do
      n < @min_rank_bars ->
        {:error, :cold, n}

      k <= 0 ->
        {:error, :cold, n}

      true ->
        thr =
          from(b in PolicyBar,
            where: b.bar_ts >= ^since and b.horizon_m == ^horizon_m,
            order_by: [desc: b.confidence],
            offset: ^(k - 1),
            limit: 1,
            select: b.confidence
          )
          |> Repo.one()

        if is_nil(thr), do: {:error, :cold, n}, else: {:ok, thr, n}
    end
  end

  @doc """
  Liveness of the signal, for `/api/health`.

  M3_PLAN §0.8 asks for exactly this and gives the reason: the served checkpoint has emitted
  no gated signal since 2026-06-29 — correctly, because the edge lives in volatile bars and
  the market has been calm since July — and **a system that has been silent for two months
  is indistinguishable from a broken one**. Reporting bars seen next to time since the last
  gated signal makes correct silence visible as correct.
  """
  def liveness(now \\ DateTime.utc_now()) do
    day_ago = DateTime.add(now, -86_400, :second)
    window_start = DateTime.add(now, -@rank_window_days * 86_400, :second)

    last_bar = Repo.one(from(b in PolicyBar, select: max(b.bar_ts)))
    last_gated = Repo.one(from(b in PolicyBar, where: b.gated == true, select: max(b.bar_ts)))
    bars_24h = Repo.aggregate(from(b in PolicyBar, where: b.bar_ts >= ^day_ago), :count)
    bars_window = Repo.aggregate(from(b in PolicyBar, where: b.bar_ts >= ^window_start), :count)

    %{
      last_bar_at: last_bar,
      last_gated_at: last_gated,
      seconds_since_last_bar: seconds_since(last_bar, now),
      seconds_since_last_gated: seconds_since(last_gated, now),
      bars_since_last_gated: bars_since(last_gated),
      bars_last_24h: bars_24h,
      bars_in_rank_window: bars_window,
      rank_window_days: @rank_window_days,
      min_rank_bars: @min_rank_bars
    }
  end

  defp seconds_since(nil, _now), do: nil
  defp seconds_since(ts, now), do: DateTime.diff(now, ts)

  defp bars_since(nil), do: nil

  defp bars_since(ts) do
    Repo.aggregate(from(b in PolicyBar, where: b.bar_ts > ^ts), :count)
  end

  @doc "Drop bars older than the retention window. Called on the policy engine's daily tick."
  def prune_bars(now \\ DateTime.utc_now()) do
    cutoff = DateTime.add(now, -@retain_days * 86_400, :second)
    {n, _} = Repo.delete_all(from(b in PolicyBar, where: b.bar_ts < ^cutoff))
    n
  end

  # ---------------------------------------------------------------- the paper ledger

  @doc "Open positions on one arm, as a list of `PaperTrade`."
  def open_trades(arm) do
    Repo.all(from(t in PaperTrade, where: t.arm == ^arm and t.status == "open"))
  end

  @doc "Pairs currently holding a position on one arm — the policy's invariant 2."
  def open_pairs(arm) do
    from(t in PaperTrade, where: t.arm == ^arm and t.status == "open", select: t.pair)
    |> Repo.all()
    |> MapSet.new()
  end

  @doc "Positions whose 4h hold has expired and which are therefore due to close."
  def due_trades(now \\ DateTime.utc_now()) do
    Repo.all(from(t in PaperTrade, where: t.status == "open" and t.exit_after_ts <= ^now))
  end

  @doc """
  Open a paper position.

  The unique partial index on (arm, pair) where status = 'open' enforces serial-per-pair in
  the database rather than only in the decision code, so a race between the 30-second poll
  and a restart cannot book two overlapping 4h holds on one pair.
  """
  def open_trade(arm, decision) do
    %PaperTrade{}
    |> PaperTrade.changeset(%{
      arm: arm,
      pair: decision.pair,
      side: decision.side,
      size: decision.size,
      entry_ts: truncate(decision.entry_ts),
      exit_after_ts: truncate(decision.exit_after_ts),
      entry_price: decision.entry_price,
      quantity: decision[:quantity],
      notional: decision[:notional],
      confidence: decision.confidence,
      threshold: decision[:threshold],
      regime: decision[:regime],
      cost_bps: ExecCost.cost_bps(decision.pair),
      status: "open"
    })
    |> Repo.insert()
  end

  @doc """
  Close a paper position at `exit_price` and book its P&L.

  Booked exactly as `backtest.py` does: `gross = side * (exit/entry - 1) * size`, and
  `net = gross - cost_bps * size` with `cost_bps` the pair's **measured** round trip from
  M3-4. The cost scales with size because a 5/3-size trade crosses 5/3 as much notional.
  """
  def close_trade(%PaperTrade{} = trade, exit_price, now \\ DateTime.utc_now()) do
    ret = exit_price / trade.entry_price - 1.0
    gross_bps = trade.side * ret * trade.size * 1.0e4
    cost_bps = trade.cost_bps || ExecCost.cost_bps(trade.pair)

    trade
    |> PaperTrade.changeset(%{
      exit_ts: truncate(now),
      exit_price: exit_price,
      gross_bps: gross_bps,
      cost_bps: cost_bps,
      net_bps: gross_bps - cost_bps * trade.size,
      status: "closed"
    })
    |> Repo.update()
  end

  @doc """
  Score one arm on the metrics M3_PROTOCOL §4 uses, so the live numbers sit next to the
  backtest ones without a translation step.

  `net_bps` here is the **per-trade mean**, which on the policy arm is a size-weighted
  average because the arm varies size. M3_2_RESULTS §D1 makes the same point about the
  offline +15.03: per unit of notional actually deployed it is +11.24. `net_bps_per_notional`
  carries that second reading, because the two answer different questions and quoting only
  the first flatters a policy that sizes up on its good bars.
  """
  def arm_summary(arm, now \\ DateTime.utc_now()) do
    closed =
      Repo.all(
        from(t in PaperTrade,
          where: t.arm == ^arm and t.status == "closed",
          order_by: [asc: t.exit_ts]
        )
      )

    n = length(closed)

    open_n =
      Repo.aggregate(from(t in PaperTrade, where: t.arm == ^arm and t.status == "open"), :count)

    first_entry = Repo.one(from(t in PaperTrade, where: t.arm == ^arm, select: min(t.entry_ts)))

    span_days =
      case first_entry do
        nil -> 0.0
        ts -> max(DateTime.diff(now, ts) / 86_400.0, 1.0)
      end

    if n == 0 do
      %{
        arm: arm,
        trades: 0,
        open: open_n,
        gross_bps: nil,
        net_bps: nil,
        net_bps_per_notional: nil,
        mean_size: nil,
        win_rate: nil,
        cum_net_bps: 0.0,
        max_drawdown_bps: 0.0,
        trades_per_day: 0.0,
        span_days: span_days
      }
    else
      nets = Enum.map(closed, & &1.net_bps)
      total_size = closed |> Enum.map(& &1.size) |> Enum.sum()

      %{
        arm: arm,
        trades: n,
        open: open_n,
        gross_bps: mean(Enum.map(closed, & &1.gross_bps)),
        net_bps: mean(nets),
        # Per unit of notional deployed: total P&L divided by total size, not by trade count.
        net_bps_per_notional: Enum.sum(nets) / total_size,
        mean_size: total_size / n,
        win_rate: Enum.count(closed, &(&1.gross_bps > 0)) / n,
        cum_net_bps: Enum.sum(nets),
        max_drawdown_bps: max_drawdown(nets),
        trades_per_day: if(span_days > 0, do: n / span_days, else: 0.0),
        span_days: span_days
      }
    end
  end

  @doc "Both arms of the A/B, side by side."
  def ab_summary(now \\ DateTime.utc_now()) do
    Enum.map(PaperTrade.arms(), &arm_summary(&1, now))
  end

  defp mean([]), do: nil
  defp mean(xs), do: Enum.sum(xs) / length(xs)

  # Peak-to-trough of the additive net-bps equity curve, in bps. Negative or zero.
  defp max_drawdown(nets) do
    {dd, _peak, _cum} =
      Enum.reduce(nets, {0.0, 0.0, 0.0}, fn x, {dd, peak, cum} ->
        cum = cum + x
        peak = max(peak, cum)
        {min(dd, cum - peak), peak, cum}
      end)

    dd
  end

  defp truncate(%DateTime{} = ts), do: DateTime.truncate(ts, :second)
end
