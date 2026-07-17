defmodule FluxTraderWeb.DashboardLive do
  @moduledoc """
  Main dashboard showing real-time market data, positions, and signals.
  """
  use FluxTraderWeb, :live_view

  @impl true
  def mount(_params, _session, socket) do
    if connected?(socket) do
      Phoenix.PubSub.subscribe(FluxTrader.PubSub, "candles:live")
    end

    {:ok,
     assign(socket,
       positions: [],
       signals: [],
       candles: %{},
       status: :connecting,
       mode: Application.get_env(:fluxtrader, :trading, []) |> Keyword.get(:mode, "simulation"),
       stats: %{open_positions: 0, daily_pnl: 0.0, leverage: 5}
     )}
  end

  @impl true
  def handle_info({:new_candle, candle}, socket) do
    candles = Map.update(socket.assigns.candles, candle.symbol, [candle], &[candle | &1])
    {:noreply, assign(socket, candles: candles, status: :connected)}
  end

  @impl true
  def render(assigns) do
    ~H"""
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:24px;">
      <div style="background:#1a1a2e;border-radius:8px;padding:20px;">
        <h2 style="color:#e94560;margin-bottom:16px;">System Status</h2>
        <div style="display:flex;gap:16px;flex-wrap:wrap;">
          <.status_badge label="Status" value={to_string(@status)} color={status_color(@status)} />
          <.status_badge label="Mode" value={@mode} color="#533483" />
          <.status_badge label="Positions" value={to_string(@stats.open_positions)} color="#0f3460" />
          <.status_badge label="Daily PnL" value={format_pnl(@stats.daily_pnl)} color={pnl_color(@stats.daily_pnl)} />
          <.status_badge label="Leverage" value={"#{@stats.leverage}x"} color="#533483" />
        </div>
      </div>

      <div style="background:#1a1a2e;border-radius:8px;padding:20px;">
        <h2 style="color:#e94560;margin-bottom:16px;">Open Positions</h2>
        <%= if @positions == [] do %>
          <p style="color:#666;">No open positions</p>
        <% else %>
          <div style="display:flex;flex-direction:column;gap:8px;">
            <%= for pos <- @positions do %>
              <div style="background:#0f0f23;padding:12px;border-radius:6px;display:flex;justify-content:space-between;">
                <span><strong><%= pos.symbol %></strong> <%= pos.side %></span>
                <span style={"color:#{pnl_color(pos.pnl)};"}><%= format_pnl(pos.pnl) %></span>
              </div>
            <% end %>
          </div>
        <% end %>
      </div>

      <div style="background:#1a1a2e;border-radius:8px;padding:20px;grid-column:1/-1;">
        <h2 style="color:#e94560;margin-bottom:16px;">Live Candles</h2>
        <%= if map_size(@candles) == 0 do %>
          <p style="color:#666;">Waiting for market data...</p>
        <% else %>
          <div style="display:grid;grid-template-columns:repeat(auto-fill, minmax(200px, 1fr));gap:12px;">
            <%= for {symbol, [latest | _]} <- @candles do %>
              <div style={"background:#0f0f23;padding:16px;border-radius:6px;border-left:4px solid #{candle_color(latest)};"}>
                <div style="font-weight:bold;margin-bottom:8px;"><%= symbol %></div>
                <div style="font-size:20px;"><%= format_price(latest.close) %></div>
                <div style="color:#888;font-size:12px;margin-top:4px;">
                  H: <%= format_price(latest.high) %> | L: <%= format_price(latest.low) %>
                </div>
                <div style="color:#888;font-size:12px;">
                  Vol: <%= format_volume(latest.volume) %>
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

  defp status_color(:connected), do: "#2ecc71"
  defp status_color(:connecting), do: "#f39c12"
  defp status_color(:error), do: "#e74c3c"
  defp status_color(_), do: "#666"

  defp pnl_color(pnl) when pnl > 0, do: "#2ecc71"
  defp pnl_color(pnl) when pnl < 0, do: "#e74c3c"
  defp pnl_color(_), do: "#888"

  defp candle_color(%{close: c, open: o}) when c > o, do: "#2ecc71"
  defp candle_color(%{close: c, open: o}) when c < o, do: "#e74c3c"
  defp candle_color(_), do: "#888"

  defp format_price(price) when is_float(price), do: :erlang.float_to_binary(price, decimals: 2)
  defp format_price(price), do: to_string(price)

  defp format_volume(vol) when is_float(vol) and vol > 1_000_000, do: "#{Float.round(vol / 1_000_000, 2)}M"
  defp format_volume(vol) when is_float(vol) and vol > 1_000, do: "#{Float.round(vol / 1_000, 2)}K"
  defp format_volume(vol), do: :erlang.float_to_binary(vol, decimals: 2)

  defp format_pnl(pnl) when is_float(pnl) do
    sign = if pnl >= 0, do: "+", else: ""
    "#{sign}#{Float.round(pnl, 2)}"
  end
  defp format_pnl(pnl), do: to_string(pnl)
end
