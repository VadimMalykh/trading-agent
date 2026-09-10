defmodule FluxTrader.Binance.UserStream do
  @moduledoc """
  The exchange's own account of what happened to our orders — the user-data stream.

  `Trading.ExchangeOrders` reconciles synchronously when it places an order, but a brake
  fires *between* ticks, and a liquidation or a manual close on the exchange never passes
  through this code at all. Position state must therefore come from the exchange, not from
  our own optimism. This consumer:

    * opens a `listenKey` (`POST /fapi/v1/listenKey`), connects to
      `wss://<host>/ws/<listenKey>`, and keeps the key alive every 30 minutes (Binance
      expires it after 60);
    * on `ORDER_TRADE_UPDATE` with a `FILLED` reduce-only / close-all order, tells
      `Trading.Executor.brake_filled/3`, which checks whether that order is the triggered
      order of an open row's stop or target algo and, if so, books the close and cancels
      the sibling brake. Our own timed close also arrives here; its row is already booked,
      so it matches nothing and is ignored;
    * on `ACCOUNT_UPDATE`, keeps the exchange's position list, and `status/0` compares it
      with the ledger's open exchange-filled rows so a mismatch is visible on
      `/api/health` rather than discovered at the next close.

  It runs only when the executor is in `auto` mode with credentials; otherwise it sits
  `:disabled` so the supervision tree is the same in every mode. Same `gun` transport and
  reconnect discipline as `Binance.WebSocket`.
  """
  use GenServer
  require Logger

  alias FluxTrader.Binance.{Client, Trade}
  alias FluxTrader.Trading.{Executor, Ledger}

  @port 443
  @reconnect_ms 5_000
  @keepalive_ms 30 * 60 * 1_000
  @recent_fills 20

  def start_link(opts), do: GenServer.start_link(__MODULE__, opts, name: __MODULE__)

  @doc "Connection state, the exchange's positions, recent fills, and ledger mismatches."
  def status do
    GenServer.call(__MODULE__, :status, 5_000)
  catch
    :exit, _ -> %{status: :unavailable}
  end

  @impl true
  def init(opts) do
    enabled? = Keyword.get(opts, :enabled, fn -> Executor.mode() == "auto" end)
    enabled? = if is_function(enabled?, 0), do: safe_bool(enabled?), else: enabled?

    state = %{
      status: :disabled,
      conn: nil,
      stream: nil,
      mref: nil,
      listen_key: nil,
      connected_at: nil,
      last_event_at: nil,
      positions: %{},
      recent_fills: [],
      client: Trade.impl()
    }

    if enabled? and Client.credentials?() do
      send(self(), :connect)
      Logger.info("Binance.UserStream starting → wss://#{Client.user_stream_host()}/ws/<listenKey>")
      {:ok, %{state | status: :connecting}}
    else
      Logger.info("Binance.UserStream disabled (mode is not auto, or no credentials)")
      {:ok, state}
    end
  end

  @impl true
  def handle_call(:status, _from, state) do
    {:reply,
     %{
       status: state.status,
       host: Client.user_stream_host(),
       connected_at: state.connected_at,
       last_event_at: state.last_event_at,
       listen_key_present: state.listen_key != nil,
       positions: state.positions,
       recent_fills: state.recent_fills,
       mismatches: if(state.status == :connected, do: mismatches(state.positions), else: [])
     }, state}
  end

  @impl true
  def handle_info(:connect, state) do
    with {:ok, %{"listenKey" => key}} <- state.client.listen_key(),
         {:ok, conn} <-
           :gun.open(String.to_charlist(Client.user_stream_host()), @port, %{
             protocols: [:http],
             transport: :tls
           }) do
      mref = Process.monitor(conn)
      Process.send_after(self(), :keepalive, @keepalive_ms)
      {:noreply, %{state | conn: conn, mref: mref, listen_key: key, status: :connecting}}
    else
      {:error, reason} ->
        Logger.warning("UserStream connect failed: #{inspect(reason)}; retrying in #{@reconnect_ms}ms")
        Process.send_after(self(), :connect, @reconnect_ms)
        {:noreply, state}

      other ->
        Logger.warning("UserStream listenKey unexpected: #{inspect(other)}; retrying")
        Process.send_after(self(), :connect, @reconnect_ms)
        {:noreply, state}
    end
  end

  def handle_info(:keepalive, %{status: :connected} = state) do
    case state.client.keepalive_listen_key() do
      {:ok, _} -> :ok
      {:error, reason} -> Logger.warning("UserStream keepalive failed: #{inspect(reason)}")
    end

    Process.send_after(self(), :keepalive, @keepalive_ms)
    {:noreply, state}
  end

  def handle_info(:keepalive, state), do: {:noreply, state}

  def handle_info({:gun_up, conn, _proto}, %{conn: conn} = state) do
    stream = :gun.ws_upgrade(conn, ~c"/ws/" ++ String.to_charlist(state.listen_key))
    {:noreply, %{state | stream: stream}}
  end

  def handle_info({:gun_upgrade, conn, stream, _protocols, _headers}, %{conn: conn, stream: stream} = state) do
    Logger.info("UserStream connected")
    {:noreply, %{state | status: :connected, connected_at: DateTime.utc_now()}}
  end

  def handle_info({:gun_ws, conn, stream, {:text, msg}}, %{conn: conn, stream: stream} = state) do
    {:noreply, handle_event(msg, %{state | last_event_at: DateTime.utc_now()})}
  end

  def handle_info({:gun_ws, _conn, _stream, {:close, code, reason}}, state) do
    Logger.warning("UserStream closed (#{code} #{inspect(reason)}); reconnecting")
    {:noreply, reconnect(state)}
  end

  def handle_info({:gun_ws, _conn, _stream, :close}, state) do
    Logger.warning("UserStream closed; reconnecting")
    {:noreply, reconnect(state)}
  end

  def handle_info({:gun_error, _conn, _stream, reason}, state) do
    Logger.warning("UserStream error: #{inspect(reason)}; reconnecting")
    {:noreply, reconnect(state)}
  end

  def handle_info({:gun_down, conn, _proto, reason, _killed}, %{conn: conn} = state) do
    Logger.warning("UserStream gun_down: #{inspect(reason)}; reconnecting")
    {:noreply, reconnect(state)}
  end

  def handle_info({:DOWN, mref, :process, conn, reason}, %{mref: mref, conn: conn} = state) do
    Logger.warning("UserStream gun process down: #{inspect(reason)}; reconnecting")
    {:noreply, reconnect(%{state | conn: nil, mref: nil})}
  end

  def handle_info(_msg, state), do: {:noreply, state}

  defp reconnect(state) do
    if state.conn, do: :gun.close(state.conn)
    if state.mref, do: Process.demonitor(state.mref, [:flush])
    Process.send_after(self(), :connect, @reconnect_ms)
    %{state | conn: nil, stream: nil, mref: nil, listen_key: nil, status: :reconnecting}
  end

  # ------------------------------------------------------------------ events

  @doc false
  def handle_event(msg, state) when is_binary(msg) do
    case Jason.decode(msg) do
      {:ok, event} -> handle_event(event, state)
      {:error, _} -> state
    end
  end

  # {"e":"ORDER_TRADE_UPDATE","o":{"s":sym,"i":orderId,"o":type,"ot":origType,"S":side,
  #   "X":status,"x":execType,"ap":avgPrice,"z":cumFilledQty,"n":commission,"N":asset,
  #   "rp":realizedPnl,"R":reduceOnly,"cp":closeAll}}
  def handle_event(%{"e" => "ORDER_TRADE_UPDATE", "o" => o}, state) do
    fill = %{
      symbol: o["s"],
      order_id: o["i"],
      type: o["o"],
      orig_type: o["ot"],
      reduce_only: o["R"] == true,
      close_all: o["cp"] == true,
      side: o["S"],
      status: o["X"],
      avg_price: to_f(o["ap"]),
      filled_qty: to_f(o["z"]),
      commission: to_f(o["n"]),
      commission_asset: o["N"],
      realized_pnl: to_f(o["rp"]),
      at: DateTime.utc_now()
    }

    Logger.info(
      "[USER-STREAM] #{fill.symbol} #{fill.type} #{fill.side} order=#{fill.order_id} " <>
        "#{fill.status} qty=#{fill.filled_qty} @ #{fill.avg_price} fee=#{fill.commission}"
    )

    closing? =
      fill.reduce_only or fill.close_all or
        fill.orig_type in ["STOP_MARKET", "TAKE_PROFIT_MARKET"] or
        fill.type in ["STOP_MARKET", "TAKE_PROFIT_MARKET"]

    if fill.status == "FILLED" and closing? and is_integer(fill.order_id) and is_binary(fill.symbol) do
      _ = safe(fn -> Executor.brake_filled(fill.symbol, fill.order_id, fill.avg_price) end)
    end

    %{state | recent_fills: Enum.take([fill | state.recent_fills], @recent_fills)}
  end

  # {"e":"ACCOUNT_UPDATE","a":{"P":[{"s":sym,"pa":positionAmt,"ep":entryPrice,"up":unrealized}]}}
  def handle_event(%{"e" => "ACCOUNT_UPDATE", "a" => %{"P" => positions}}, state) do
    updated =
      Enum.reduce(positions, state.positions, fn p, acc ->
        amt = to_f(p["pa"])

        if amt == 0.0 do
          Map.delete(acc, p["s"])
        else
          Map.put(acc, p["s"], %{
            amount: amt,
            entry_price: to_f(p["ep"]),
            unrealized_pnl: to_f(p["up"])
          })
        end
      end)

    %{state | positions: updated}
  end

  def handle_event(%{"e" => "listenKeyExpired"}, state) do
    Logger.warning("UserStream listenKey expired; reconnecting with a new one")
    reconnect(state)
  end

  def handle_event(_event, state), do: state

  # Exchange positions against the ledger's open exchange-filled rows, both directions.
  defp mismatches(positions) do
    ledger =
      safe(fn -> Ledger.open_trades("policy") end) ||
        []

    ledger_syms = ledger |> Enum.filter(&(&1.fill_source == "exchange")) |> MapSet.new(& &1.pair)
    exchange_syms = MapSet.new(Map.keys(positions))

    Enum.map(MapSet.difference(exchange_syms, ledger_syms), &%{symbol: &1, on: :exchange_only}) ++
      Enum.map(MapSet.difference(ledger_syms, exchange_syms), &%{symbol: &1, on: :ledger_only})
  end

  defp safe(fun) do
    fun.()
  rescue
    _ -> nil
  catch
    :exit, _ -> nil
  end

  defp safe_bool(fun), do: safe(fun) == true

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
