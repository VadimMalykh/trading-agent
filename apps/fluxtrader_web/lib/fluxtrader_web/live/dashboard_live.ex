defmodule FluxTraderWeb.DashboardLive do
  @moduledoc """
  Dashboard: candles, M2 signals, positions.
  """
  use FluxTraderWeb, :live_view
  require Logger

  @refresh_ms 15_000

  @impl true
  def mount(_params, _session, socket) do
    if connected?(socket) do
      Logger.info("DashboardLive mounted (connected) — subscribing to PubSub")
      Phoenix.PubSub.subscribe(FluxTrader.PubSub, "candles:live")
      Phoenix.PubSub.subscribe(FluxTrader.PubSub, "signals:live")
      Process.send_after(self(), :refresh_candles, @refresh_ms)
    else
      Logger.info("DashboardLive mounted (static render)")
    end

    candles = safe_candles()
    engine = safe_engine()
    status = if map_size(candles) > 0, do: :connected, else: :connecting
    positions = safe_positions()
    signals = if is_map(engine.signals), do: Map.values(engine.signals), else: []

    {:ok,
     assign(socket,
       positions: positions,
       signals: signals,
       inference_ok: engine.inference_ok,
       inference_error: engine.last_error,
       candles: candles,
       status: status,
       mode: Application.get_env(:fluxtrader, :trading, []) |> Keyword.get(:mode, "simulation"),
       last_updated: DateTime.utc_now(),
       stats: %{
         open_positions: length(positions),
         daily_pnl: 0.0,
         leverage: Application.get_env(:fluxtrader, :trading, []) |> Keyword.get(:leverage, 5)
       }
     )}
  end

  @impl true
  def handle_info({:new_candle, candle}, socket) do
    if candle_interval(candle) in [nil, "1m"] do
      Logger.debug("DashboardLive got candle #{candle_symbol(candle)} close=#{inspect(Map.get(candle, :close))}")
      candles = Map.put(socket.assigns.candles, candle_symbol(candle), [normalize_candle(candle)])
      {:noreply, assign(socket, candles: candles, status: :connected, last_updated: DateTime.utc_now())}
    else
      {:noreply, socket}
    end
  end

  def handle_info({:signal, signal}, socket) do
    signals =
      socket.assigns.signals
      |> Enum.reject(&(&1.symbol == signal.symbol))
      |> Kernel.++([signal])

    positions = safe_positions()

    {:noreply,
     assign(socket,
       signals: signals,
       inference_ok: true,
       inference_error: nil,
       positions: positions,
       last_updated: DateTime.utc_now(),
       stats: %{socket.assigns.stats | open_positions: length(positions)}
     )}
  end

  def handle_info(:refresh_candles, socket) do
    # Reschedule first so a crash/timeout later cannot kill the poll loop forever
    Process.send_after(self(), :refresh_candles, @refresh_ms)

    candles =
      case safe_candles() do
        map when map_size(map) > 0 -> map
        _ -> socket.assigns.candles
      end

    status = if map_size(candles) > 0, do: :connected, else: socket.assigns.status
    engine = safe_engine()
    positions = safe_positions()

    # Never wipe good signals on a transient engine timeout
    {signals, inference_ok, inference_error} =
      cond do
        engine.ok? and is_map(engine.signals) ->
          {Map.values(engine.signals), engine.inference_ok, engine.last_error}

        true ->
          {socket.assigns.signals, socket.assigns.inference_ok,
           engine.last_error || socket.assigns.inference_error}
      end

    {:noreply,
     assign(socket,
       candles: candles,
       status: status,
       signals: signals,
       inference_ok: inference_ok,
       inference_error: inference_error,
       positions: positions,
       last_updated: DateTime.utc_now(),
       stats: %{socket.assigns.stats | open_positions: length(positions)}
     )}
  end

  def handle_info(_msg, socket), do: {:noreply, socket}

  @impl true
  def terminate(reason, _socket) do
    Logger.info("DashboardLive terminate: #{inspect(reason)}")
    :ok
  end

  @impl true
  def render(assigns) do
    ~H"""
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:24px;">
      <div style="background:#1a1a2e;border-radius:8px;padding:20px;">
        <h2 style="color:#e94560;margin-bottom:16px;">System Status</h2>
        <div style="display:flex;gap:16px;flex-wrap:wrap;">
          <.status_badge label="Data" value={to_string(@status)} color={status_color(@status)} />
          <.status_badge label="Mode" value={@mode} color="#533483" />
          <.status_badge
            label="ML"
            value={if @inference_ok, do: "online", else: "offline"}
            color={if @inference_ok, do: "#2ecc71", else: "#e74c3c"}
          />
          <.status_badge label="Positions" value={to_string(@stats.open_positions)} color="#0f3460" />
          <.status_badge label="Leverage" value={"#{@stats.leverage}x"} color="#533483" />
        </div>
        <%= if @inference_error do %>
          <p style="color:#e74c3c;font-size:12px;margin-top:12px;"><%= @inference_error %></p>
        <% end %>
      </div>

      <div style="background:#1a1a2e;border-radius:8px;padding:20px;">
        <h2 style="color:#e94560;margin-bottom:16px;">Open Positions (sim)</h2>
        <%= if @positions == [] do %>
          <p style="color:#666;">No open positions</p>
        <% else %>
          <div style="display:flex;flex-direction:column;gap:8px;">
            <%= for pos <- @positions do %>
              <div style="background:#0f0f23;padding:12px;border-radius:6px;display:flex;justify-content:space-between;">
                <span><strong><%= pos.symbol %></strong> <%= pos.side %></span>
                <span style={"color:#{pnl_color(Map.get(pos, :pnl, 0.0))};"}>
                  <%= format_pnl(Map.get(pos, :pnl, 0.0)) %>
                </span>
              </div>
            <% end %>
          </div>
        <% end %>
      </div>

      <div style="background:#1a1a2e;border-radius:8px;padding:20px;grid-column:1/-1;">
        <h2 style="color:#e94560;margin-bottom:16px;">M2 Signals (gated simulation)</h2>
        <%= if @signals == [] do %>
          <p style="color:#666;">
            Waiting for inference… Ensure ml_inference is up and m2_multi.pt exists.
          </p>
        <% else %>
          <div style="display:grid;grid-template-columns:repeat(auto-fill, minmax(260px, 1fr));gap:12px;">
            <%= for s <- Enum.sort_by(@signals, & &1.symbol) do %>
              <div style={"background:#0f0f23;padding:16px;border-radius:6px;border-left:4px solid #{signal_color(s)};"}>
                <div style="display:flex;justify-content:space-between;margin-bottom:8px;">
                  <strong><%= s.symbol %></strong>
                  <span style={"color:#{signal_color(s)};font-weight:bold;"}><%= s.side %></span>
                </div>
                <div style="font-size:13px;color:#aaa;">
                  conf=<%= format_conf(s.confidence) %>
                  · gate=<%= format_conf(s.gate_threshold) %>
                  · <%= if s.trade, do: "TRADE", else: "SKIP" %>
                </div>
                <div style="font-size:12px;color:#666;margin-top:6px;">
                  px=<%= format_price(s.price) %> · primary <%= s.primary_horizon_m %>m
                </div>
                <%= if is_map(s.horizons) and map_size(s.horizons) > 0 do %>
                  <div style="font-size:11px;color:#888;margin-top:8px;line-height:1.5;">
                    <%= for {h, hv} <- Enum.sort(s.horizons) do %>
                      <div>
                        <%= h %>m: <%= horizon_dir(hv) %>
                        (<%= format_conf(horizon_conf(hv)) %>)
                        <%= if horizon_gated(hv), do: "✓", else: "" %>
                      </div>
                    <% end %>
                  </div>
                <% end %>
              </div>
            <% end %>
          </div>
        <% end %>
      </div>

      <div style="background:#1a1a2e;border-radius:8px;padding:20px;grid-column:1/-1;">
        <h2 style="color:#e94560;margin-bottom:16px;">Live Candles (1m)</h2>
        <%= if map_size(@candles) == 0 do %>
          <p style="color:#666;">Waiting for market data...</p>
        <% else %>
          <div style="display:grid;grid-template-columns:repeat(auto-fill, minmax(200px, 1fr));gap:12px;">
            <%= for {symbol, [latest | _]} <- Enum.sort(@candles) do %>
              <div style={"background:#0f0f23;padding:16px;border-radius:6px;border-left:4px solid #{candle_color(latest)};"}>
                <div style="font-weight:bold;margin-bottom:8px;"><%= symbol %></div>
                <div style="font-size:20px;"><%= format_price(latest.close) %></div>
                <div style="color:#888;font-size:12px;margin-top:4px;">
                  O: <%= format_price(latest.open) %> H: <%= format_price(latest.high) %> L: <%= format_price(latest.low) %>
                </div>
              </div>
            <% end %>
          </div>
        <% end %>
      </div>
    </div>
    """
  end

  defp status_badge(assigns) do
    ~H"""
    <div style={"background:#{@color}22;padding:8px 16px;border-radius:20px;border:1px solid #{@color};color:#{@color};font-size:13px;"}>
      <span style="opacity:0.7;"><%= @label %>:</span> <strong><%= @value %></strong>
    </div>
    """
  end

  defp safe_candles do
    try do
      FluxTrader.Data.Candles.latest_by_symbol("1m")
    rescue
      e ->
        Logger.warning("candles refresh failed: #{Exception.message(e)}")
        %{}
    catch
      :exit, reason ->
        Logger.warning("candles refresh exit: #{inspect(reason)}")
        %{}
    end
  end

  defp safe_engine do
    try do
      result = FluxTrader.ML.SignalEngine.latest()
      Map.put(result, :ok?, true)
    rescue
      e ->
        Logger.warning("engine latest failed: #{Exception.message(e)}")
        %{signals: nil, inference_ok: false, last_error: "engine error", last_run_at: nil, ok?: false}
    catch
      :exit, reason ->
        Logger.warning("engine latest exit: #{inspect(reason)}")
        %{signals: nil, inference_ok: false, last_error: "engine busy/down", last_run_at: nil, ok?: false}
    end
  end

  defp safe_positions do
    try do
      FluxTrader.Trading.Executor.get_positions()
    rescue
      _ -> []
    catch
      :exit, _ -> []
    end
  end

  defp candle_interval(c) when is_map(c), do: Map.get(c, :interval) || Map.get(c, "interval")
  defp candle_interval(_), do: nil

  defp candle_symbol(c) when is_map(c), do: Map.get(c, :symbol) || Map.get(c, "symbol")
  defp candle_symbol(_), do: nil

  defp normalize_candle(c) when is_map(c) do
    %{
      symbol: Map.get(c, :symbol) || Map.get(c, "symbol"),
      open: Map.get(c, :open) || Map.get(c, "open"),
      high: Map.get(c, :high) || Map.get(c, "high"),
      low: Map.get(c, :low) || Map.get(c, "low"),
      close: Map.get(c, :close) || Map.get(c, "close"),
      volume: Map.get(c, :volume) || Map.get(c, "volume")
    }
  end

  defp horizon_dir(%{"direction" => d}), do: d
  defp horizon_dir(%{direction: d}), do: d
  defp horizon_dir(_), do: "?"

  defp horizon_conf(%{"confidence" => c}) when is_number(c), do: c
  defp horizon_conf(%{confidence: c}) when is_number(c), do: c
  defp horizon_conf(_), do: 0.0

  defp horizon_gated(%{"gated" => g}), do: g
  defp horizon_gated(%{gated: g}), do: g
  defp horizon_gated(_), do: false

  defp signal_color(%{side: "BUY"}), do: "#2ecc71"
  defp signal_color(%{side: "SELL"}), do: "#e74c3c"
  defp signal_color(_), do: "#888"

  defp status_color(:connected), do: "#2ecc71"
  defp status_color(:connecting), do: "#f39c12"
  defp status_color(_), do: "#666"

  defp pnl_color(pnl) when is_number(pnl) and pnl > 0, do: "#2ecc71"
  defp pnl_color(pnl) when is_number(pnl) and pnl < 0, do: "#e74c3c"
  defp pnl_color(_), do: "#888"

  defp candle_color(%{close: c, open: o}) when is_number(c) and is_number(o) and c > o, do: "#2ecc71"
  defp candle_color(%{close: c, open: o}) when is_number(c) and is_number(o) and c < o, do: "#e74c3c"
  defp candle_color(_), do: "#888"

  defp format_price(nil), do: "-"
  defp format_price(p) when is_float(p), do: :erlang.float_to_binary(p, decimals: 2)
  defp format_price(p), do: to_string(p)

  defp format_conf(nil), do: "-"
  defp format_conf(c) when is_float(c), do: :erlang.float_to_binary(c, decimals: 3)
  defp format_conf(c) when is_integer(c), do: Integer.to_string(c)
  defp format_conf(c), do: to_string(c)

  defp format_pnl(pnl) when is_float(pnl) do
    sign = if pnl >= 0, do: "+", else: ""
    "#{sign}#{Float.round(pnl, 2)}"
  end

  defp format_pnl(pnl), do: to_string(pnl)
end
