defmodule FluxTraderWeb.SettingsLive do
  @moduledoc """
  Settings page. Whitelist and trading prefs persist in Postgres.
  """
  use FluxTraderWeb, :live_view

  @impl true
  def mount(_params, _session, socket) do
    if connected?(socket) do
      Phoenix.PubSub.subscribe(FluxTrader.PubSub, "settings:whitelist")
    end

    trading = FluxTrader.Settings.get_trading()
    pairs = FluxTrader.Pairs.Selector.active_pairs()

    {:ok,
     assign(socket,
       trading_mode: trading["mode"] || "simulation",
       max_positions: trading["max_positions"] || 3,
       stop_loss_pct: trading["stop_loss_pct"] || 0.02,
       take_profit_ratio: trading["take_profit_ratio"] || 2.0,
       leverage: trading["leverage"] || 5,
       whitelist_pairs: pairs,
       flash_msg: nil,
       saved: false
     )}
  end

  @impl true
  def render(assigns) do
    ~H"""
    <div style="max-width:800px;">
      <h1 style="color:#e94560;margin-bottom:24px;">Settings</h1>

      <%= if @flash_msg do %>
        <div style="background:#16213e;padding:12px;border-radius:6px;margin-bottom:16px;border-left:4px solid #2ecc71;">
          <%= @flash_msg %>
        </div>
      <% end %>

      <div style="background:#1a1a2e;border-radius:8px;padding:24px;margin-bottom:24px;">
        <h2 style="margin-bottom:16px;">Trading Mode</h2>
        <div style="display:flex;gap:12px;flex-wrap:wrap;">
          <%= for mode <- ["simulation", "signal", "manual", "auto"] do %>
            <button
              type="button"
              phx-click="set_mode"
              phx-value-mode={mode}
              style={"background:#{if @trading_mode == mode, do: "#e94560", else: "#0f3460"};color:white;border:none;padding:10px 20px;border-radius:6px;cursor:pointer;font-weight:bold;"}
            >
              <%= String.capitalize(mode) %>
            </button>
          <% end %>
        </div>
        <p style="color:#888;font-size:13px;margin-top:8px;">
          Current: <strong><%= @trading_mode %></strong>
          <%= if @trading_mode == "auto" do %>
            <span style="color:#e74c3c;">(requires backtest validation)</span>
          <% end %>
        </p>
      </div>

      <div style="background:#1a1a2e;border-radius:8px;padding:24px;margin-bottom:24px;">
        <h2 style="margin-bottom:16px;">Risk Parameters</h2>
        <form phx-change="update_risk" style="display:grid;grid-template-columns:1fr 1fr;gap:16px;">
          <div>
            <label style="color:#888;font-size:13px;">Max Positions</label>
            <input type="number" name="max_positions" value={@max_positions}
              style="width:100%;background:#0f0f23;border:1px solid #333;color:white;padding:8px 12px;border-radius:4px;" />
          </div>
          <div>
            <label style="color:#888;font-size:13px;">Stop Loss %</label>
            <input type="number" name="stop_loss_pct" value={@stop_loss_pct} step="0.01"
              style="width:100%;background:#0f0f23;border:1px solid #333;color:white;padding:8px 12px;border-radius:4px;" />
          </div>
          <div>
            <label style="color:#888;font-size:13px;">Take Profit Ratio</label>
            <input type="number" name="take_profit_ratio" value={@take_profit_ratio} step="0.1"
              style="width:100%;background:#0f0f23;border:1px solid #333;color:white;padding:8px 12px;border-radius:4px;" />
          </div>
          <div>
            <label style="color:#888;font-size:13px;">Leverage</label>
            <input type="number" name="leverage" value={@leverage} min="1" max="20"
              style="width:100%;background:#0f0f23;border:1px solid #333;color:white;padding:8px 12px;border-radius:4px;" />
          </div>
        </form>
      </div>

      <div style="background:#1a1a2e;border-radius:8px;padding:24px;">
        <h2 style="margin-bottom:16px;">Whitelist Pairs</h2>
        <p style="color:#888;font-size:13px;margin-bottom:12px;">
          Saved to database. Collector and signals use this list after refresh/restart.
        </p>
        <div style="display:flex;gap:8px;flex-wrap:wrap;">
          <%= for pair <- @whitelist_pairs do %>
            <span style="background:#0f3460;padding:6px 12px;border-radius:20px;font-size:13px;display:flex;align-items:center;gap:6px;">
              <%= pair %>
              <button type="button" phx-click="remove_pair" phx-value-pair={pair}
                style="background:none;border:none;color:#e74c3c;cursor:pointer;font-size:16px;">
                ×
              </button>
            </span>
          <% end %>
        </div>
        <form phx-submit="add_pair" style="margin-top:12px;display:flex;gap:8px;">
          <input type="text" name="pair" placeholder="e.g. DOGEUSDT" required
            style="flex:1;background:#0f0f23;border:1px solid #333;color:white;padding:8px 12px;border-radius:4px;" />
          <button type="submit"
            style="background:#533483;color:white;border:none;padding:8px 16px;border-radius:4px;cursor:pointer;">
            Add
          </button>
        </form>
      </div>
    </div>
    """
  end

  @impl true
  def handle_event("set_mode", %{"mode" => mode}, socket) do
    FluxTrader.Settings.put_trading(%{"mode" => mode})
    {:noreply, assign(socket, trading_mode: mode, flash_msg: "Mode saved: #{mode}", saved: true)}
  end

  def handle_event("update_risk", params, socket) do
    max_pos = parse_int(params["max_positions"], socket.assigns.max_positions)
    sl = parse_float(params["stop_loss_pct"], socket.assigns.stop_loss_pct)
    tp = parse_float(params["take_profit_ratio"], socket.assigns.take_profit_ratio)
    lev = parse_int(params["leverage"], socket.assigns.leverage)

    FluxTrader.Settings.put_trading(%{
      "max_positions" => max_pos,
      "stop_loss_pct" => sl,
      "take_profit_ratio" => tp,
      "leverage" => lev,
      "mode" => socket.assigns.trading_mode
    })

    {:noreply,
     assign(socket,
       max_positions: max_pos,
       stop_loss_pct: sl,
       take_profit_ratio: tp,
       leverage: lev,
       flash_msg: "Risk settings saved",
       saved: true
     )}
  end

  def handle_event("add_pair", %{"pair" => pair}, socket) do
    pair = String.upcase(String.trim(pair))

    case FluxTrader.Pairs.Selector.add_pair(pair) do
      {:ok, pairs} ->
        {:noreply,
         assign(socket,
           whitelist_pairs: pairs,
           flash_msg: "Added #{pair} (persisted)",
           saved: true
         )}

      _ ->
        {:noreply, assign(socket, flash_msg: "Could not add pair")}
    end
  end

  def handle_event("remove_pair", %{"pair" => pair}, socket) do
    case FluxTrader.Pairs.Selector.remove_pair(pair) do
      {:ok, pairs} ->
        {:noreply,
         assign(socket,
           whitelist_pairs: pairs,
           flash_msg: "Removed #{pair} (persisted)",
           saved: true
         )}

      _ ->
        {:noreply, socket}
    end
  end

  @impl true
  def handle_info({:whitelist, pairs}, socket) do
    {:noreply, assign(socket, whitelist_pairs: pairs)}
  end

  def handle_info(_, socket), do: {:noreply, socket}

  defp parse_int(nil, default), do: default
  defp parse_int("", default), do: default

  defp parse_int(val, default) when is_binary(val) do
    case Integer.parse(val) do
      {n, _} -> n
      :error -> default
    end
  end

  defp parse_int(val, _) when is_integer(val), do: val
  defp parse_int(_, default), do: default

  defp parse_float(nil, default), do: default
  defp parse_float("", default), do: default

  defp parse_float(val, default) when is_binary(val) do
    case Float.parse(val) do
      {n, _} -> n
      :error -> default
    end
  end

  defp parse_float(val, _) when is_float(val), do: val
  defp parse_float(val, _) when is_integer(val), do: val * 1.0
  defp parse_float(_, default), do: default
end
