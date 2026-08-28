defmodule FluxTrader.Trading.Regime do
  @moduledoc """
  The one regime observable the policy is allowed to use: **`btc_absret_1d`**, the absolute
  return of Bitcoin over the trailing 24 hours.

  ## Why only this one

  NEXT_TRAINING_PLAN §1.8 tested ten observables. `btc_absret_1d` is the only one that was
  monotone, seed-stable and reproducible; the rest were U-shaped, unstable across seeds, or
  flat, and the model's own trailing confidence was *anti*-predictive in all three seeds.
  `ml/train/m3/regime.py` rebuilds the others only so that finding can be re-checked, and
  says in as many words that a policy should not condition on them. This module therefore
  serves one number.

  ## How it is computed here, and why not from our own database

  Offline, the observable is built from the prediction dumps by shifting `fwd_ret` back one
  day — free, and lookahead-free by construction. Live there is no dump, so it comes from
  Binance's own 5-minute klines: `|close(t) / close(t - 288 bars) - 1|`. Two reasons to go to
  the exchange rather than to our candles table:

    * it is **re-derivable after a restart**, so a redeploy does not cost 30 days of warmup
      the way an in-memory-only history would;
    * it does not depend on our collector having been up, which decouples the policy's
      sizing from a data-collection outage.

  The quintile **edges** are taken over the trailing 30 days of bars — a distribution of
  market states, never of the bars the model happened to gate (`backtest.py` is emphatic
  about this: a quantile over selected trades is conditioned on the model and is not a
  statement about the market).

  §1.8's published 80th-percentile cut was **4.31%** over the evaluation period. `edges/0`
  will not reproduce that today and is not supposed to — August 2026 is the calmest stretch
  of the whole period, with `btc_absret_1d` averaging 0.0070 against 0.011-0.027 earlier —
  but a top edge far away from 4.31% is worth noticing, and `/api/health` reports it.
  """
  use GenServer
  require Logger

  alias FluxTrader.Trading.Policy

  @bar_interval "5m"
  @bars_per_day 288
  @history_days 30
  @symbol "BTCUSDT"
  @refresh_ms 60_000
  # Below this many samples the quintile edges are noise, so the policy stays cold rather
  # than sizing off four points. 7 days of bars.
  @min_samples 7 * @bars_per_day
  @published_p80 0.0431

  def start_link(opts), do: GenServer.start_link(__MODULE__, opts, name: __MODULE__)

  @doc """
  Current `btc_absret_1d`, the quintile edges, and whether there is enough history to size
  on. `{:ok, %{value: float, edges: [float], samples: n}}` or `{:error, :cold}`.
  """
  def state, do: GenServer.call(__MODULE__, :state, 10_000)

  @doc "Status for /api/health. Never errors, never blocks on a cold start."
  def status do
    GenServer.call(__MODULE__, :status, 10_000)
  catch
    :exit, _ -> %{ready: false, error: "regime process unavailable"}
  end

  @impl true
  def init(_opts) do
    # Bootstrapping hits the REST API ~7 times, so it runs out of `init` rather than in it:
    # a slow or rate-limited exchange must not stop the supervision tree from starting.
    send(self(), :bootstrap)
    {:ok, %{closes: %{}, edges: nil, value: nil, last_error: nil, bootstrapped: false}}
  end

  @impl true
  def handle_call(:state, _from, state) do
    reply =
      if ready?(state) do
        {:ok, %{value: state.value, edges: state.edges, samples: map_size(state.closes)}}
      else
        {:error, :cold}
      end

    {:reply, reply, state}
  end

  def handle_call(:status, _from, state) do
    {:reply,
     %{
       ready: ready?(state),
       btc_absret_1d: state.value,
       quintile_edges: state.edges,
       # The p80 edge against §1.8's published 4.31%: a large gap means the market is in a
       # different volatility regime from the one the policy was measured in.
       p80_edge: state.edges && List.last(state.edges),
       published_p80: @published_p80,
       close_bars: map_size(state.closes),
       min_bars: @min_samples + @bars_per_day,
       last_error: state.last_error
     }, state}
  end

  @impl true
  def handle_info(:bootstrap, state) do
    state = refresh(state, @history_days * @bars_per_day + @bars_per_day)
    Process.send_after(self(), :tick, @refresh_ms)
    {:noreply, %{state | bootstrapped: true}}
  end

  def handle_info(:tick, state) do
    # 300 bars is 25 hours, enough to close any gap shorter than a day without refetching
    # the whole history. A longer outage is repaired by the next restart's bootstrap.
    state = refresh(state, 300)
    Process.send_after(self(), :tick, @refresh_ms)
    {:noreply, state}
  end

  def handle_info(_msg, state), do: {:noreply, state}

  defp ready?(state) do
    state.edges != nil and state.value != nil and
      map_size(state.closes) >= @min_samples + @bars_per_day
  end

  defp refresh(state, want_bars) do
    case fetch_closes(want_bars) do
      {:ok, closes} when closes != %{} ->
        merged = state.closes |> Map.merge(closes) |> prune()
        series = absret_series(merged)

        case Policy.quintile_edges(Map.values(series)) do
          {:ok, edges} ->
            value = latest_value(series)
            %{state | closes: merged, edges: edges, value: value, last_error: nil}

          {:error, :empty} ->
            %{state | closes: merged, last_error: "no absret samples yet"}
        end

      {:ok, _empty} ->
        %{state | last_error: "klines returned no bars"}

      {:error, reason} ->
        msg = "regime refresh failed: #{inspect(reason)}"
        Logger.warning(msg)
        %{state | last_error: msg}
    end
  end

  # Binance caps `limit` at 1500, so a 31-day pull is walked backwards in pages.
  defp fetch_closes(want_bars) do
    do_fetch(want_bars, nil, %{})
  end

  defp do_fetch(remaining, _end_time, acc) when remaining <= 0, do: {:ok, acc}

  defp do_fetch(remaining, end_time, acc) do
    limit = min(remaining, 1500)
    opts = [limit: limit] ++ if(end_time, do: [end_time: end_time], else: [])

    case FluxTrader.Binance.Client.klines(@symbol, @bar_interval, opts) do
      {:ok, rows} when is_list(rows) and rows != [] ->
        parsed =
          Enum.reduce(rows, %{}, fn row, m ->
            case row do
              [open_ms, _o, _h, _l, close | _] ->
                Map.put(m, div(open_ms, 1000), to_float(close))

              _ ->
                m
            end
          end)

        acc = Map.merge(acc, parsed)
        oldest = parsed |> Map.keys() |> Enum.min(fn -> nil end)

        # Only page again if this response was full; a short one means we hit the start of
        # available history and looping would spin.
        if oldest && length(rows) >= limit and remaining - length(rows) > 0 do
          do_fetch(remaining - length(rows), (oldest - 1) * 1000, acc)
        else
          {:ok, acc}
        end

      {:ok, other} ->
        {:error, {:unexpected_klines, other}}

      {:error, reason} ->
        {:error, reason}
    end
  end

  defp to_float(v) when is_binary(v), do: String.to_float(v)
  defp to_float(v) when is_number(v), do: v * 1.0

  defp prune(closes) do
    cutoff =
      System.system_time(:second) - (@history_days + 1) * @bars_per_day * Policy.bar_seconds()

    :maps.filter(fn ts, _ -> ts >= cutoff end, closes)
  end

  @doc false
  # |close(t)/close(t-24h) - 1| for every bar whose lookback is complete. Bars with a gap in
  # the history are simply absent rather than interpolated: a fabricated close would feed a
  # fabricated size multiplier.
  def absret_series(closes) do
    lag = @bars_per_day * Policy.bar_seconds()

    closes
    |> Enum.reduce(%{}, fn {ts, close}, acc ->
      case Map.fetch(closes, ts - lag) do
        {:ok, past} when past > 0 -> Map.put(acc, ts, abs(close / past - 1.0))
        _ -> acc
      end
    end)
  end

  defp latest_value(series) when map_size(series) == 0, do: nil

  defp latest_value(series) do
    {_ts, v} = Enum.max_by(series, fn {ts, _} -> ts end)
    v
  end
end
