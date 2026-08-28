defmodule FluxTrader.MarketData.Collector do
  @moduledoc """
  Polls Binance Futures public REST for M1 market data and persists to Postgres.
  No API keys required.
  """
  use GenServer
  require Logger

  alias FluxTrader.Binance.Client

  alias FluxTrader.MarketData.{
    BookFeatures,
    LongShortRatio,
    MarketTrade,
    OrderbookSnapshot,
    OrderbookLevel,
    FundingRate,
    OpenInterest
  }

  alias FluxTrader.Data.Candle
  alias FluxTrader.Repo

  @book_interval_ms 5_000
  @trade_interval_ms 5_000
  @slow_interval_ms 60_000
  @ratio_interval_ms 60_000

  # Positioning / sentiment ratios (B4.2, docs/BOOK_ERA_PLAN.md).
  #
  # The exchange's minimum granularity is 5m and it retains only ~30 days, so:
  #   * polling faster than the bucket only refreshes the still-forming bucket,
  #     which is why the poll upserts rather than inserts;
  #   * the one-time backfill below is the ONLY chance to capture the ~30 days
  #     that already exist. After that, history accrues only because we poll.
  @ratio_period "5m"
  # Last few buckets each poll: cheap, and it lets a bucket that was still
  # forming when we first saw it be corrected once it closes.
  @ratio_poll_limit 3
  @ratio_backfill_days 30
  # Exchange cap on `limit` for /futures/data/*.
  @ratio_backfill_page 500
  # Politeness pause between backfill pages — the backfill is ~18 pages x 3
  # endpoints x n_pairs and must not crowd out the 5s book/trade polls' rate
  # budget. It runs off-process (Task.Supervisor), so this sleep blocks nothing.
  @ratio_backfill_sleep_ms 200

  # Depth levels to fetch per book poll. Fetch DEEP for the lossless raw ladder
  # (OrderbookLevel); the compressed scalar features stay pinned to the top 20 in
  # BookFeatures to preserve the served model's semantics. Tunable via config
  # :fluxtrader, :book_depth_limit. See docs/DATA_COLLECTION_AUDIT.md.
  @default_book_depth_limit 100

  # aggTrades to fetch per 5s tape poll. Binance returns the *most recent* N, so a limit
  # below the pair's actual 5s trade count silently discards the OLDEST trades and the
  # derived high/low/volume describe only what survived. M3-4a measured the old limit of
  # 200 right-censoring 30.4% of BTC windows, 29.3% ZEC, 28.0% ETH — concentrated in
  # exactly the busy windows that matter. 1000 is the endpoint's maximum. Tunable via
  # config :fluxtrader, :trade_tape_limit. See docs/M3_4_PROTOCOL.md §1.2.
  @default_trade_tape_limit 1000

  def start_link(opts) do
    GenServer.start_link(__MODULE__, opts, name: __MODULE__)
  end

  @impl true
  def init(_opts) do
    pairs = pairs()

    state = %{
      pairs: pairs,
      last_trade_ids: %{},
      # Pairs whose one-time ~30-day ratio backfill has already been kicked off.
      # Guards against re-running it every time the whitelist changes.
      ratio_backfilled: MapSet.new(),
      # Monitor ref of the in-flight ratio poll, or nil. See start_ratio_poll/1.
      ratio_poll: nil
    }

    Phoenix.PubSub.subscribe(FluxTrader.PubSub, "settings:whitelist")

    # Backfill history once so M1 training has enough samples without waiting hours
    Process.send_after(self(), :backfill_history, 500)
    Process.send_after(self(), :poll_book, 1_000)
    Process.send_after(self(), :poll_trades, 2_000)
    Process.send_after(self(), :poll_slow, 3_000)
    Process.send_after(self(), :poll_candles, 4_000)
    Process.send_after(self(), :poll_ratios, 5_000)

    Logger.info("MarketData.Collector started for #{inspect(pairs)}")
    {:ok, state}
  end

  def handle_info({:whitelist, pairs}, state) do
    Logger.info("Collector whitelist updated: #{inspect(pairs)}")
    # Backfill new pairs shortly
    Process.send_after(self(), :backfill_history, 1_000)
    {:noreply, %{state | pairs: pairs}}
  end

  def handle_info(:backfill_history, state) do
    state = sync_pairs(state)
    Logger.info("Backfilling historical klines for M1...")

    Enum.each(state.pairs, fn pair ->
      try do
        backfill_candles(pair, "1m", 500)
        backfill_candles(pair, "5m", 500)
        backfill_candles(pair, "15m", 500)
        backfill_candles(pair, "1h", 500)
        collect_book(pair)
        collect_funding(pair)
        collect_open_interest(pair)
      rescue
        e ->
          Logger.error("Backfill crashed for #{pair}: #{Exception.message(e)}")
      end
    end)

    Logger.info("Historical backfill complete")
    {:noreply, backfill_ratios_async(state)}
  end

  @impl true
  def handle_info(:poll_book, state) do
    state = sync_pairs(state)
    Enum.each(state.pairs, &collect_book/1)
    Process.send_after(self(), :poll_book, @book_interval_ms)
    {:noreply, state}
  end

  def handle_info(:poll_trades, state) do
    state = sync_pairs(state)

    state =
      Enum.reduce(state.pairs, state, fn pair, acc ->
        case collect_trades(pair, Map.get(acc.last_trade_ids, pair)) do
          {:ok, last_id} ->
            %{acc | last_trade_ids: Map.put(acc.last_trade_ids, pair, last_id)}

          :ok ->
            acc

          {:error, _} ->
            acc
        end
      end)

    Process.send_after(self(), :poll_trades, @trade_interval_ms)
    {:noreply, state}
  end

  def handle_info(:poll_slow, state) do
    state = sync_pairs(state)

    Enum.each(state.pairs, fn pair ->
      collect_funding(pair)
      collect_open_interest(pair)
      # Liquidations are collected via Binance.WebSocket (!forceOrder@arr);
      # the REST allForceOrders endpoint is auth-gated / unusable for public data.
    end)

    Process.send_after(self(), :poll_slow, @slow_interval_ms)
    {:noreply, state}
  end

  def handle_info(:poll_candles, state) do
    state = sync_pairs(state)

    Enum.each(state.pairs, fn pair ->
      try do
        collect_candles(pair, "1m")
        collect_candles(pair, "5m")
        collect_candles(pair, "15m")
        collect_candles(pair, "1h")
      rescue
        e -> Logger.warning("poll_candles crashed for #{pair}: #{Exception.message(e)}")
      catch
        :exit, reason -> Logger.warning("poll_candles exit for #{pair}: #{inspect(reason)}")
      end
    end)

    Process.send_after(self(), :poll_candles, @slow_interval_ms)
    {:noreply, state}
  end

  def handle_info(:poll_ratios, state) do
    state = sync_pairs(state)
    Process.send_after(self(), :poll_ratios, @ratio_interval_ms)
    {:noreply, state |> start_ratio_poll() |> backfill_ratios_async()}
  end

  def handle_info({:DOWN, ref, :process, _pid, _reason}, %{ratio_poll: ref} = state) do
    {:noreply, %{state | ratio_poll: nil}}
  end

  def handle_info(_msg, state), do: {:noreply, state}

  defp sync_pairs(state) do
    %{state | pairs: pairs()}
  end

  defp pairs do
    try do
      FluxTrader.Pairs.Selector.active_pairs()
    rescue
      _ ->
        Application.get_env(:fluxtrader, :trading, [])
        |> Keyword.get(:whitelist_pairs, ["BTCUSDT", "ETHUSDT", "SOLUSDT"])
    catch
      :exit, _ ->
        Application.get_env(:fluxtrader, :trading, [])
        |> Keyword.get(:whitelist_pairs, ["BTCUSDT", "ETHUSDT", "SOLUSDT"])
    end
  end

  defp collect_book(symbol) do
    case Client.order_book(symbol, book_depth_limit()) do
      {:ok, depth} ->
        case BookFeatures.from_depth(symbol, depth) do
          {:ok, features} ->
            %OrderbookSnapshot{}
            |> OrderbookSnapshot.changeset(features)
            |> Repo.insert(on_conflict: :nothing, conflict_target: [:symbol, :ts])

            # Persist the FULL raw ladder losslessly, sharing the snapshot's ts so
            # the two tables join 1:1 on (symbol, ts). Best-effort: a raw-ladder
            # failure must not drop the scalar snapshot.
            persist_raw_levels(symbol, depth, features.ts)

            Phoenix.PubSub.broadcast(FluxTrader.PubSub, "market:book", {:book, features})

          {:error, reason} ->
            Logger.debug("Book features skip #{symbol}: #{inspect(reason)}")
        end

      {:error, reason} ->
        Logger.warning("Book poll failed #{symbol}: #{inspect(reason)}")
    end
  end

  defp persist_raw_levels(symbol, depth, ts) do
    case BookFeatures.raw_levels(symbol, depth, ts) do
      {:ok, attrs} ->
        %OrderbookLevel{}
        |> OrderbookLevel.changeset(attrs)
        |> Repo.insert(on_conflict: :nothing, conflict_target: [:symbol, :ts])

      {:error, reason} ->
        Logger.debug("Raw book levels skip #{symbol}: #{inspect(reason)}")
    end
  end

  defp book_depth_limit do
    Application.get_env(:fluxtrader, :book_depth_limit, @default_book_depth_limit)
  end

  defp trade_tape_limit do
    Application.get_env(:fluxtrader, :trade_tape_limit, @default_trade_tape_limit)
  end

  defp collect_trades(symbol, last_id) do
    opts = [limit: trade_tape_limit()]

    case Client.agg_trades(symbol, opts) do
      {:ok, trades} when is_list(trades) and trades != [] ->
        trades =
          if last_id do
            Enum.filter(trades, fn t -> Map.get(t, "a", 0) > last_id end)
          else
            trades
          end

        if trades == [] do
          :ok
        else
          window = aggregate_trades(symbol, trades)
          max_id = trades |> Enum.map(&Map.get(&1, "a", 0)) |> Enum.max()

          %MarketTrade{}
          |> MarketTrade.changeset(window)
          |> Repo.insert(on_conflict: :nothing, conflict_target: [:symbol, :window_start])

          {:ok, max_id}
        end

      {:ok, _} ->
        :ok

      {:error, reason} ->
        Logger.warning("Trades poll failed #{symbol}: #{inspect(reason)}")
        {:error, reason}
    end
  end

  defp aggregate_trades(symbol, trades) do
    prices = Enum.map(trades, &to_f(Map.get(&1, "p")))
    qtys = Enum.map(trades, &to_f(Map.get(&1, "q")))

    {buy_vol, sell_vol} =
      Enum.zip(trades, qtys)
      |> Enum.reduce({0.0, 0.0}, fn {t, q}, {b, s} ->
        # m = true means buyer is market maker => seller aggressor
        if Map.get(t, "m") == true, do: {b, s + q}, else: {b + q, s}
      end)

    volume = Enum.sum(qtys)
    notional = Enum.zip(prices, qtys) |> Enum.reduce(0.0, fn {p, q}, acc -> acc + p * q end)
    vwap = if volume > 0, do: notional / volume, else: List.last(prices) || 0.0
    ts = trades |> List.last() |> Map.get("T") |> ms_to_dt()

    %{
      symbol: symbol,
      window_start: floor_to_5s(ts),
      trade_count: length(trades),
      volume: volume,
      buy_volume: buy_vol,
      sell_volume: sell_vol,
      vwap: vwap,
      high: Enum.max(prices),
      low: Enum.min(prices)
    }
  end

  defp collect_funding(symbol) do
    case Client.premium_index(symbol) do
      {:ok, data} when is_map(data) ->
        attrs = %{
          symbol: symbol,
          ts: DateTime.utc_now() |> DateTime.truncate(:microsecond),
          # Exchange clock alongside the local one (B4.1). `ts` is unchanged.
          event_time: ms_to_dt(Map.get(data, "time")),
          mark_price: to_f(Map.get(data, "markPrice")),
          index_price: to_f(Map.get(data, "indexPrice")),
          last_funding_rate: to_f(Map.get(data, "lastFundingRate")),
          next_funding_time: ms_to_dt(Map.get(data, "nextFundingTime"))
        }

        %FundingRate{}
        |> FundingRate.changeset(attrs)
        |> Repo.insert(on_conflict: :nothing, conflict_target: [:symbol, :ts])

      {:error, reason} ->
        Logger.warning("Funding poll failed #{symbol}: #{inspect(reason)}")

      _ ->
        :ok
    end
  end

  defp collect_open_interest(symbol) do
    case Client.open_interest(symbol) do
      {:ok, data} when is_map(data) ->
        attrs = %{
          symbol: symbol,
          ts: DateTime.utc_now() |> DateTime.truncate(:microsecond),
          # Exchange clock alongside the local one (B4.1). `ts` is unchanged.
          event_time: ms_to_dt(Map.get(data, "time")),
          open_interest: to_f(Map.get(data, "openInterest"))
        }

        %OpenInterest{}
        |> OpenInterest.changeset(attrs)
        |> Repo.insert(on_conflict: :nothing, conflict_target: [:symbol, :ts])

      {:error, reason} ->
        Logger.warning("OI poll failed #{symbol}: #{inspect(reason)}")

      _ ->
        :ok
    end
  end

  # --- Positioning / sentiment ratios (B4.2) --------------------------------
  #
  # Three /futures/data endpoints share one row per (symbol, exchange bucket ts,
  # period). Each writes ONLY its own column group via `on_conflict: {:replace,
  # ...}`, so one endpoint failing or lagging never blanks another's values, and
  # re-polling a still-forming bucket corrects it in place.

  # Off the GenServer on purpose. This is 3 requests x n_pairs; run inline it can
  # stall the loop for seconds and the 5s book poll slips with it — which would
  # add exactly the collection jitter B4.1 exists to remove. The overlap guard
  # keeps a slow exchange from piling up ticks; a skipped tick costs nothing,
  # since each poll re-reads the last @ratio_poll_limit buckets anyway.
  defp start_ratio_poll(%{ratio_poll: ref} = state) when is_reference(ref) do
    Logger.debug("Ratio poll still in flight; skipping this tick")
    state
  end

  defp start_ratio_poll(state) do
    pairs = state.pairs

    case Task.Supervisor.start_child(FluxTrader.TaskSupervisor, fn ->
           Enum.each(pairs, &collect_ratios/1)
         end) do
      {:ok, pid} -> %{state | ratio_poll: Process.monitor(pid)}
      _ -> state
    end
  end

  defp collect_ratios(symbol) do
    opts = [period: @ratio_period, limit: @ratio_poll_limit]

    fetch_ratio(:top, symbol, opts) |> persist_ratios(:top, symbol)
    fetch_ratio(:global, symbol, opts) |> persist_ratios(:global, symbol)
    fetch_ratio(:taker, symbol, opts) |> persist_ratios(:taker, symbol)
  end

  defp fetch_ratio(:top, symbol, opts), do: Client.top_long_short_account_ratio(symbol, opts)
  defp fetch_ratio(:global, symbol, opts), do: Client.global_long_short_account_ratio(symbol, opts)
  defp fetch_ratio(:taker, symbol, opts), do: Client.taker_long_short_ratio(symbol, opts)

  defp persist_ratios({:ok, rows}, kind, symbol) when is_list(rows) do
    Enum.each(rows, &persist_ratio(kind, symbol, &1))
  end

  defp persist_ratios({:error, reason}, kind, symbol) do
    Logger.warning("Ratio poll failed #{symbol}/#{kind}: #{inspect(reason)}")
  end

  defp persist_ratios(_, _kind, _symbol), do: :ok

  defp persist_ratio(:top, symbol, row) do
    upsert_ratio(
      %{
        top_long_short_ratio: to_f_or_nil(Map.get(row, "longShortRatio")),
        top_long_account: to_f_or_nil(Map.get(row, "longAccount")),
        top_short_account: to_f_or_nil(Map.get(row, "shortAccount"))
      },
      symbol,
      Map.get(row, "timestamp"),
      [:top_long_short_ratio, :top_long_account, :top_short_account]
    )
  end

  defp persist_ratio(:global, symbol, row) do
    upsert_ratio(
      %{
        global_long_short_ratio: to_f_or_nil(Map.get(row, "longShortRatio")),
        global_long_account: to_f_or_nil(Map.get(row, "longAccount")),
        global_short_account: to_f_or_nil(Map.get(row, "shortAccount"))
      },
      symbol,
      Map.get(row, "timestamp"),
      [:global_long_short_ratio, :global_long_account, :global_short_account]
    )
  end

  defp persist_ratio(:taker, symbol, row) do
    upsert_ratio(
      %{
        taker_buy_sell_ratio: to_f_or_nil(Map.get(row, "buySellRatio")),
        taker_buy_vol: to_f_or_nil(Map.get(row, "buyVol")),
        taker_sell_vol: to_f_or_nil(Map.get(row, "sellVol"))
      },
      symbol,
      Map.get(row, "timestamp"),
      [:taker_buy_sell_ratio, :taker_buy_vol, :taker_sell_vol]
    )
  end

  defp upsert_ratio(values, symbol, timestamp_ms, replace_fields) do
    case ms_to_dt(to_int(timestamp_ms)) do
      nil ->
        :ok

      ts ->
        attrs = Map.merge(values, %{symbol: symbol, ts: ts, period: @ratio_period})

        %LongShortRatio{}
        |> LongShortRatio.changeset(attrs)
        |> Repo.insert(
          on_conflict: {:replace, replace_fields},
          conflict_target: [:symbol, :ts, :period]
        )
        |> case do
          {:ok, _} -> :ok
          {:error, cs} -> Logger.debug("Ratio insert rejected #{symbol}: #{inspect(cs.errors)}")
        end
    end
  end

  # One-time capture of the ~30 days the exchange still holds. Runs off the
  # GenServer (Task.Supervisor) because it is ~18 pages x 3 endpoints x n_pairs
  # with a politeness sleep between pages — blocking the collector loop for that
  # long would stall the 5s book/trade polls.
  defp backfill_ratios_async(state) do
    case Enum.reject(state.pairs, &MapSet.member?(state.ratio_backfilled, &1)) do
      [] ->
        state

      new_pairs ->
        Logger.info("Backfilling #{@ratio_backfill_days}d of long/short ratios for #{inspect(new_pairs)}")

        Task.Supervisor.start_child(FluxTrader.TaskSupervisor, fn ->
          # Serial across pairs and endpoints on purpose: concurrent pages would
          # multiply the request rate by n_pairs against a shared IP budget.
          Enum.each(new_pairs, &backfill_ratios/1)
          Logger.info("Long/short ratio backfill complete for #{inspect(new_pairs)}")
        end)

        %{state | ratio_backfilled: MapSet.union(state.ratio_backfilled, MapSet.new(new_pairs))}
    end
  end

  defp backfill_ratios(symbol) do
    now_ms = System.system_time(:millisecond)
    start_ms = now_ms - @ratio_backfill_days * 86_400_000

    Enum.each([:top, :global, :taker], fn kind ->
      try do
        backfill_ratio_kind(symbol, kind, start_ms, now_ms)
      rescue
        e -> Logger.warning("Ratio backfill crashed #{symbol}/#{kind}: #{Exception.message(e)}")
      catch
        :exit, reason -> Logger.warning("Ratio backfill exit #{symbol}/#{kind}: #{inspect(reason)}")
      end
    end)
  end

  # Pages BACKWARD, and that is not a style choice. Verified against the live
  # endpoint 2026-08-24: given startTime 30d ago, endTime now and limit 500, it
  # returns the 500 buckets ending at endTime (~42h) — it does NOT return the
  # oldest 500 from startTime. Paging forward from startTime therefore never
  # reaches the past and would silently capture only the last ~42h of a window we
  # get exactly one chance to collect. So walk endTime down instead.
  defp backfill_ratio_kind(symbol, kind, start_ms, end_ms) when start_ms < end_ms do
    opts = [
      period: @ratio_period,
      limit: @ratio_backfill_page,
      start_time: start_ms,
      end_time: end_ms
    ]

    case fetch_ratio(kind, symbol, opts) do
      {:ok, rows} when is_list(rows) and rows != [] ->
        Enum.each(rows, &persist_ratio(kind, symbol, &1))

        timestamps =
          rows
          |> Enum.map(&to_int(Map.get(&1, "timestamp")))
          |> Enum.reject(&is_nil/1)

        Process.sleep(@ratio_backfill_sleep_ms)

        # Drop end_ms strictly below the oldest bucket seen, so the window shrinks
        # on every recursion and this terminates (the start_ms < end_ms guard is
        # the floor). A short page means the window is exhausted — the exchange
        # has no more history.
        cond do
          timestamps == [] -> :ok
          length(rows) < @ratio_backfill_page -> :ok
          true -> backfill_ratio_kind(symbol, kind, start_ms, Enum.min(timestamps) - 1)
        end

      {:error, reason} ->
        Logger.warning("Ratio backfill failed #{symbol}/#{kind}: #{inspect(reason)}")

      _ ->
        :ok
    end
  end

  defp backfill_ratio_kind(_symbol, _kind, _start_ms, _end_ms), do: :ok

  defp collect_candles(symbol, interval) do
    case Client.klines(symbol, interval, limit: 5) do
      {:ok, rows} when is_list(rows) ->
        Enum.each(rows, &insert_candle(symbol, interval, &1, broadcast: interval == "1m"))

      {:error, reason} ->
        Logger.warning("Candle poll failed #{symbol}/#{interval}: #{inspect(reason)}")

      _ ->
        :ok
    end
  end

  defp backfill_candles(symbol, interval, limit) do
    case Client.klines(symbol, interval, limit: limit) do
      {:ok, rows} when is_list(rows) ->
        Enum.each(rows, &insert_candle(symbol, interval, &1, broadcast: false))
        Logger.info("Backfilled #{length(rows)} #{interval} candles for #{symbol}")

      {:error, reason} ->
        Logger.warning("Backfill failed #{symbol}/#{interval}: #{inspect(reason)}")

      _ ->
        :ok
    end
  end

  defp insert_candle(symbol, interval, kline, opts) do
    candle = parse_kline(symbol, interval, kline)

    try do
      %Candle{}
      |> Candle.changeset(candle)
      |> Repo.insert(on_conflict: :nothing, conflict_target: [:symbol, :interval, :open_time])
    rescue
      e -> Logger.warning("candle insert failed #{symbol}/#{interval}: #{Exception.message(e)}")
    catch
      :exit, reason -> Logger.warning("candle insert exit #{symbol}/#{interval}: #{inspect(reason)}")
    end

    if Keyword.get(opts, :broadcast, false) do
      Phoenix.PubSub.broadcast(FluxTrader.PubSub, "candles:live", {:new_candle, candle})
    end
  end

  defp parse_kline(symbol, interval, kline) when is_list(kline) do
    %{
      symbol: symbol,
      interval: interval,
      open_time: ms_to_dt(Enum.at(kline, 0)),
      open: to_f(Enum.at(kline, 1)),
      high: to_f(Enum.at(kline, 2)),
      low: to_f(Enum.at(kline, 3)),
      close: to_f(Enum.at(kline, 4)),
      volume: to_f(Enum.at(kline, 5)),
      close_time: ms_to_dt(Enum.at(kline, 6))
    }
  end

  defp floor_to_5s(%DateTime{} = dt) do
    unix = DateTime.to_unix(dt)
    floored = div(unix, 5) * 5
    DateTime.from_unix!(floored) |> DateTime.truncate(:microsecond)
  end

  defp floor_to_5s(_), do: DateTime.utc_now() |> DateTime.truncate(:microsecond)

  defp ms_to_dt(nil), do: nil
  defp ms_to_dt(ms) when is_integer(ms), do: DateTime.from_unix!(ms, :millisecond) |> DateTime.truncate(:microsecond)
  defp ms_to_dt(_), do: nil

  defp to_f(nil), do: 0.0
  defp to_f(v) when is_float(v), do: v
  defp to_f(v) when is_integer(v), do: v * 1.0

  defp to_f(v) when is_binary(v) do
    case Float.parse(v) do
      {f, _} -> f
      :error -> 0.0
    end
  end

  defp to_f(_), do: 0.0

  # Ratio columns are documented as "nil = that endpoint has not answered for this
  # bucket". to_f/1 would turn a missing field into a confident 0.0 and quietly
  # break that reading, so ratio values go through this instead.
  defp to_f_or_nil(nil), do: nil
  defp to_f_or_nil(v) when is_float(v), do: v
  defp to_f_or_nil(v) when is_integer(v), do: v * 1.0

  defp to_f_or_nil(v) when is_binary(v) do
    case Float.parse(v) do
      {f, _} -> f
      :error -> nil
    end
  end

  defp to_f_or_nil(_), do: nil

  # Unlike to_f/1 this returns nil rather than 0 on garbage: a missing exchange
  # timestamp must skip the row, not become 1970.
  defp to_int(v) when is_integer(v), do: v

  defp to_int(v) when is_binary(v) do
    case Integer.parse(v) do
      {int, _} -> int
      :error -> nil
    end
  end

  defp to_int(_), do: nil
end
