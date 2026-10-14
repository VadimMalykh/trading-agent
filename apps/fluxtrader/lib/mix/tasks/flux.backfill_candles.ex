defmodule Mix.Tasks.Flux.BackfillCandles do
  @shortdoc "Re-fetch the last N hours of klines for every collected pair, repairing missing bars"
  @moduledoc """
  Fill candle holes left by an outage.

      docker compose exec app mix flux.backfill_candles --hours 30
      docker compose exec app mix flux.backfill_candles --hours 30 --intervals 1m,5m --pairs BTCUSDT,ETHUSDT

  The live poll asks for the last 5 bars each minute, so an outage longer than five minutes
  leaves bars that nothing refetches (2026-10-13: 313 1m and 12 5m bars across the twelve
  pairs, during the two IP bans). `/fapi/v1/klines` keeps full history, so a window re-read
  with `startTime` paging lands every bar through `Collector.store_candle/1`'s replace.

  Starts the app WITHOUT its workers (no second collector), so it is safe beside the running
  one; it shares the IP's request budget and goes through `Binance.RateLimit` like every
  other call. Cost: ≈ 15 weight a pair for 30 hours over the four intervals.
  """

  use Mix.Task
  import Ecto.Query

  alias FluxTrader.Binance.RateLimit
  alias FluxTrader.Data.Candle
  alias FluxTrader.MarketData.Collector
  alias FluxTrader.Repo

  @intervals ~w(1m 5m 15m 1h)
  @page 1_000
  @page_weight 5

  @impl Mix.Task
  def run(argv) do
    {opts, _, _} =
      OptionParser.parse(argv, strict: [hours: :integer, intervals: :string, pairs: :string])

    hours = Keyword.get(opts, :hours, 30)
    intervals = opts |> Keyword.get(:intervals, Enum.join(@intervals, ",")) |> String.split(",")

    Mix.Task.run("app.config")
    Application.put_env(:fluxtrader, :start_workers, false)
    {:ok, _} = Application.ensure_all_started(:fluxtrader)

    pairs =
      case Keyword.get(opts, :pairs) do
        nil -> collected_pairs()
        s -> String.split(s, ",")
      end

    now_ms = System.system_time(:millisecond)
    start_ms = now_ms - hours * 3_600_000
    IO.puts("Backfilling #{inspect(intervals)} for #{length(pairs)} pairs from #{DateTime.from_unix!(start_ms, :millisecond)}")

    for pair <- pairs, interval <- intervals do
      n = backfill(pair, interval, start_ms, now_ms)
      IO.puts("  #{pair} #{interval}: #{n} bars")
    end
  end

  defp backfill(pair, interval, from_ms, now_ms) do
    step = interval_ms(interval)

    Stream.iterate(from_ms, &(&1 + @page * step))
    |> Stream.take_while(&(&1 < now_ms))
    |> Enum.reduce(0, fn page_start, acc ->
      RateLimit.wait(@page_weight, RateLimit.cap(:trades))

      case Collector.backfill_candles(pair, interval, @page, start_time: page_start) do
        {:ok, n} -> acc + n
        {:error, reason} -> Mix.raise("#{pair}/#{interval} at #{page_start}: #{inspect(reason)}")
      end
    end)
  end

  defp collected_pairs do
    since = DateTime.add(DateTime.utc_now(), -2, :day)

    Repo.all(
      from c in Candle,
        where: c.interval == "1m" and c.open_time > ^since,
        distinct: true,
        select: c.symbol,
        order_by: c.symbol
    )
  end

  defp interval_ms("1m"), do: 60_000
  defp interval_ms("5m"), do: 300_000
  defp interval_ms("15m"), do: 900_000
  defp interval_ms("1h"), do: 3_600_000
end
