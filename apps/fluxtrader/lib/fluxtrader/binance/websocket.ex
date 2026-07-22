defmodule FluxTrader.Binance.WebSocket do
  @moduledoc """
  Binance futures data feed. Uses REST polling with periodic refresh.
  """
  use GenServer
  require Logger

  @poll_interval_ms 60_000

  def start_link(opts) do
    GenServer.start_link(__MODULE__, opts, name: __MODULE__)
  end

  def subscribe(streams) do
    GenServer.cast(__MODULE__, {:subscribe, streams})
  end

  @impl true
  def init(_opts) do
    {:ok, %{streams: [], pairs: []}, {:continue, :start_polling}}
  end

  @impl true
  def handle_continue(:start_polling, state) do
    config = Application.get_env(:fluxtrader, :trading, [])
    pairs = Keyword.get(config, :whitelist_pairs, ["BTCUSDT", "ETHUSDT", "SOLUSDT"])
    state = %{state | pairs: pairs}

    Task.Supervisor.async_nolink(FluxTrader.TaskSupervisor, fn -> poll_klines(pairs) end)

    schedule_poll()
    {:noreply, state}
  end

  @impl true
  def handle_info(:poll, state) do
    Task.Supervisor.async_nolink(FluxTrader.TaskSupervisor, fn -> poll_klines(state.pairs) end)
    schedule_poll()
    {:noreply, state}
  end

  def handle_info({:DOWN, _ref, :process, _pid, _reason}, state) do
    {:noreply, state}
  end

  def handle_info({ref, result}, state) when is_reference(ref) do
    case result do
      :ok -> Logger.debug("Poll completed successfully")
      {:error, reason} -> Logger.warning("Poll failed: #{inspect(reason)}")
    end
    {:noreply, state}
  end

  def handle_info({:EXIT, _pid, _reason}, state) do
    {:noreply, state}
  end

  @impl true
  def handle_cast({:subscribe, streams}, state) do
    {:noreply, %{state | streams: state.streams ++ streams}}
  end

  defp poll_klines(pairs) do
    # Only 1m on candles:live — dashboard overwrites per-symbol and would show
    # stale 5m/1h closes if higher TFs were broadcast on the same topic.
    interval = "1m"

    for pair <- pairs do
      case FluxTrader.Binance.Client.klines(pair, interval, limit: 1) do
        {:ok, [kline | _]} ->
          candle = parse_kline(pair, interval, kline)
          Phoenix.PubSub.broadcast(FluxTrader.PubSub, "candles:live", {:new_candle, candle})

        {:ok, other} ->
          Logger.warning(
            "Unexpected kline response for #{pair}/#{interval}: #{inspect(other) |> String.slice(0, 200)}"
          )

        {:error, reason} ->
          Logger.warning("Failed to fetch klines for #{pair}/#{interval}: #{inspect(reason)}")
      end
    end

    :ok
  end

  defp parse_kline(symbol, interval, kline) when is_list(kline) do
    %{
      symbol: symbol,
      interval: interval,
      open_time: DateTime.from_unix!(Enum.at(kline, 0), :millisecond),
      open: to_f(Enum.at(kline, 1)),
      high: to_f(Enum.at(kline, 2)),
      low: to_f(Enum.at(kline, 3)),
      close: to_f(Enum.at(kline, 4)),
      volume: to_f(Enum.at(kline, 5)),
      close_time: DateTime.from_unix!(Enum.at(kline, 6), :millisecond)
    }
  end

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

  defp schedule_poll do
    Process.send_after(self(), :poll, @poll_interval_ms)
  end
end
