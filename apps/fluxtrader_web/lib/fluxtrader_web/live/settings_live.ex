defmodule FluxTraderWeb.SettingsLive do
  @moduledoc """
  Settings page for API keys, trading mode, risk parameters, and pair whitelist.
  """
  use FluxTraderWeb, :live_view

  @impl true
  def mount(_params, _session, socket) do
    config = Application.get_env(:fluxtrader, :trading, [])

    {:ok,
     assign(socket,
       trading_mode: Keyword.get(config, :mode, "simulation"),
       max_positions: Keyword.get(config, :max_positions, 3),
       stop_loss_pct: Keyword.get(config, :stop_loss_pct, 0.02),
       take_profit_ratio: Keyword.get(config, :take_profit_ratio, 2.0),
       leverage: Keyword.get(config, :leverage, 5),
       whitelist_pairs: Keyword.get(config, :whitelist_pairs, ["BTCUSDT", "ETHUSDT", "SOLUSDT"]),
       saved: false
     )}
  end

  @impl true
  def render(assigns) do
    ~H"""
    <div style="max-width:800px;">
      <h1 style="color:#e94560;margin-bottom:24px;">Settings</h1>

      <div style="background:#1a1a2e;border-radius:8px;padding:24px;margin-bottom:24px;">
        <h2 style="margin-bottom:16px;">Trading Mode</h2>
        <div style="display:flex;gap:12px;flex-wrap:wrap;">
          <%= for mode <- ["simulation", "signal", "manual", "auto"] do %>
            <button
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
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;">
          <div>
            <label style="color:#888;font-size:13px;">Max Positions</label>
            <input type="number" value={@max_positions} phx-change="update_max_positions"
              style="width:100%;background:#0f0f23;border:1px solid #333;color:white;padding:8px 12px;border-radius:4px;" />
          </div>
          <div>
            <label style="color:#888;font-size:13px;">Stop Loss %</label>
            <input type="number" value={@stop_loss_pct} step="0.01" phx-change="update_stop_loss"
              style="width:100%;background:#0f0f23;border:1px solid #333;color:white;padding:8px 12px;border-radius:4px;" />
          </div>
          <div>
            <label style="color:#888;font-size:13px;">Take Profit Ratio</label>
            <input type="number" value={@take_profit_ratio} step="0.1" phx-change="update_take_profit"
              style="width:100%;background:#0f0f23;border:1px solid #333;color:white;padding:8px 12px;border-radius:4px;" />
          </div>
          <div>
            <label style="color:#888;font-size:13px;">Leverage</label>
            <input type="number" value={@leverage} min="1" max="10" phx-change="update_leverage"
              style="width:100%;background:#0f0f23;border:1px solid #333;color:white;padding:8px 12px;border-radius:4px;" />
          </div>
        </div>
      </div>

      <div style="background:#1a1a2e;border-radius:8px;padding:24px;">
        <h2 style="margin-bottom:16px;">Whitelist Pairs</h2>
        <div style="display:flex;gap:8px;flex-wrap:wrap;">
          <%= for pair <- @whitelist_pairs do %>
            <span style="background:#0f3460;padding:6px 12px;border-radius:20px;font-size:13px;display:flex;align-items:center;gap:6px;">
              <%= pair %>
              <button phx-click="remove_pair" phx-value-pair={pair}
                style="background:none;border:none;color:#e74c3c;cursor:pointer;font-size:16px;">
                x
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
    {:noreply, assign(socket, trading_mode: mode, saved: true)}
  end

  def handle_event("update_max_positions", %{"value" => val}, socket) do
    {:noreply, assign(socket, max_positions: String.to_integer(val), saved: true)}
  end

  def handle_event("update_stop_loss", %{"value" => val}, socket) do
    {:noreply, assign(socket, stop_loss_pct: Float.parse(val) |> elem(0), saved: true)}
  end

  def handle_event("update_take_profit", %{"value" => val}, socket) do
    {:noreply, assign(socket, take_profit_ratio: Float.parse(val) |> elem(0), saved: true)}
  end

  def handle_event("update_leverage", %{"value" => val}, socket) do
    {:noreply, assign(socket, leverage: String.to_integer(val), saved: true)}
  end

  def handle_event("add_pair", %{"pair" => pair}, socket) do
    pair = String.upcase(String.trim(pair))

    if pair not in socket.assigns.whitelist_pairs do
      {:noreply, assign(socket, whitelist_pairs: socket.assigns.whitelist_pairs ++ [pair])}
    else
      {:noreply, socket}
    end
  end

  def handle_event("remove_pair", %{"pair" => pair}, socket) do
    pairs = Enum.reject(socket.assigns.whitelist_pairs, &(&1 == pair))
    {:noreply, assign(socket, whitelist_pairs: pairs)}
  end
end
