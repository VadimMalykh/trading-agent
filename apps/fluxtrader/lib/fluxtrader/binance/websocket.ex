defmodule FluxTrader.Binance.WebSocket do
  @moduledoc """
  Binance Futures liquidation feed consumer.

  Liquidations are **only** available in real time via the WebSocket
  `!forceOrder@arr` (all-market) stream — the REST `allForceOrders` endpoint is
  auth-gated and effectively unusable for public market-wide data, and there is
  **no historical backfill**. Every gap is permanently lost, so this runs as a
  persistent, auto-reconnecting consumer.

  Events feed the `liquidations` table → M2 microstructure features → M3 (RL)
  policy inputs. Keep it collecting continuously.

  Uses `gun` for the WS transport. Other market data (candles, book, trades,
  funding, OI) is still polled by `MarketData.Collector`.
  """
  use GenServer
  require Logger

  alias FluxTrader.MarketData.Liquidation
  alias FluxTrader.Repo

  @host ~c"fstream.binance.com"
  @port 443
  # Connect to the bare /ws endpoint and SUBSCRIBE explicitly — more robust than
  # embedding the stream in the path (which silently yields no frames for
  # !forceOrder@arr on some edges).
  @path ~c"/ws"
  @stream_name "!forceOrder@arr"
  @reconnect_ms 5_000
  # Binance closes idle connections after 24h and sends ping frames; gun answers
  # pings automatically. We also self-heal on any gun_down/ws close.

  def start_link(opts) do
    GenServer.start_link(__MODULE__, opts, name: __MODULE__)
  end

  @impl true
  def init(_opts) do
    state = %{conn: nil, stream: nil, mref: nil, status: :connecting}
    send(self(), :connect)
    Logger.info("Binance.WebSocket (liquidation feed) starting → wss://#{@host}#{@path} (#{@stream_name})")
    {:ok, state}
  end

  @impl true
  def handle_info(:connect, state) do
    case :gun.open(@host, @port, %{protocols: [:http], transport: :tls}) do
      {:ok, conn} ->
        mref = Process.monitor(conn)
        {:noreply, %{state | conn: conn, mref: mref, status: :connecting}}

      {:error, reason} ->
        Logger.warning("Liquidation WS open failed: #{inspect(reason)}; retrying in #{@reconnect_ms}ms")
        Process.send_after(self(), :connect, @reconnect_ms)
        {:noreply, state}
    end
  end

  # gun connection is up → upgrade to WebSocket
  def handle_info({:gun_up, conn, _proto}, %{conn: conn} = state) do
    stream = :gun.ws_upgrade(conn, @path)
    {:noreply, %{state | stream: stream}}
  end

  def handle_info({:gun_upgrade, conn, stream, _protocols, _headers}, %{conn: conn, stream: stream} = state) do
    sub = Jason.encode!(%{"method" => "SUBSCRIBE", "params" => [@stream_name], "id" => 1})
    :gun.ws_send(conn, stream, {:text, sub})
    Logger.info("Liquidation WS upgraded; sent SUBSCRIBE #{@stream_name}")
    {:noreply, %{state | status: :connected}}
  end

  def handle_info({:gun_ws, conn, stream, {:text, msg}}, %{conn: conn, stream: stream} = state) do
    handle_event(msg)
    {:noreply, state}
  end

  def handle_info({:gun_ws, _conn, _stream, {:close, code, reason}}, state) do
    Logger.warning("Liquidation WS closed (#{code} #{inspect(reason)}); reconnecting")
    {:noreply, reconnect(state)}
  end

  def handle_info({:gun_ws, _conn, _stream, :close}, state) do
    Logger.warning("Liquidation WS closed; reconnecting")
    {:noreply, reconnect(state)}
  end

  def handle_info({:gun_error, _conn, _stream, reason}, state) do
    Logger.warning("Liquidation WS error: #{inspect(reason)}; reconnecting")
    {:noreply, reconnect(state)}
  end

  def handle_info({:gun_down, conn, _proto, reason, _killed}, %{conn: conn} = state) do
    Logger.warning("Liquidation WS gun_down: #{inspect(reason)}; reconnecting")
    {:noreply, reconnect(state)}
  end

  def handle_info({:DOWN, mref, :process, conn, reason}, %{mref: mref, conn: conn} = state) do
    Logger.warning("Liquidation WS gun process down: #{inspect(reason)}; reconnecting")
    {:noreply, reconnect(%{state | conn: nil, mref: nil})}
  end

  def handle_info(_msg, state), do: {:noreply, state}

  defp reconnect(state) do
    if state.conn, do: :gun.close(state.conn)
    if state.mref, do: Process.demonitor(state.mref, [:flush])
    Process.send_after(self(), :connect, @reconnect_ms)
    %{state | conn: nil, stream: nil, mref: nil, status: :reconnecting}
  end

  # Binance forceOrder event:
  # {"e":"forceOrder","E":<eventTime ms>,
  #  "o":{"s":"BTCUSDT","S":"SELL","q":"0.014","p":"9910","ap":"9910.5","T":<tradeTime ms>,...}}
  defp handle_event(msg) do
    with {:ok, %{"e" => "forceOrder", "o" => o}} <- Jason.decode(msg) do
      persist(o)
    else
      _ -> :ok
    end
  rescue
    e -> Logger.debug("Liquidation event parse error: #{Exception.message(e)}")
  end

  defp persist(o) do
    symbol = Map.get(o, "s")
    ts = ms_to_dt(Map.get(o, "T") || Map.get(o, "E"))

    if symbol && ts do
      attrs = %{
        symbol: symbol,
        ts: ts,
        # A "SELL" force order = a long being liquidated (forced sell); "BUY" = short liquidated.
        side: Map.get(o, "S"),
        # Average fill price if present, else order price.
        price: to_f(Map.get(o, "ap") || Map.get(o, "p")),
        quantity: to_f(Map.get(o, "q")),
        order_id: ""
      }

      %Liquidation{}
      |> Liquidation.changeset(attrs)
      |> Repo.insert()
      |> case do
        {:ok, _} -> :ok
        {:error, cs} -> Logger.debug("Liquidation insert rejected: #{inspect(cs.errors)}")
      end
    end
  end

  defp ms_to_dt(nil), do: nil

  defp ms_to_dt(ms) when is_integer(ms),
    do: DateTime.from_unix!(ms, :millisecond) |> DateTime.truncate(:microsecond)

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
end
