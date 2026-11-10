defmodule FluxTraderWeb.AccountLive do
  @moduledoc """
  The shared USDⓈ-M account: closed deals per month, bot and manual, as % of the notional
  deposit, and the notional deposit itself (which also sizes the live pilot). See
  `FluxTrader.Account.Stats` for what counts and `FluxTrader.Account.Deals` for what a deal is.
  """
  use FluxTraderWeb, :live_view

  alias FluxTrader.Account.{NotionalDeposit, Stats, Sync}
  alias FluxTrader.Trading.LivePilot

  @impl true
  def mount(_params, _session, socket) do
    if connected?(socket), do: Phoenix.PubSub.subscribe(FluxTrader.PubSub, Sync.topic())
    {:ok, socket |> assign(flash_msg: nil, refreshing: false) |> load()}
  end

  defp load(socket) do
    deals = Stats.deals()
    hist = NotionalDeposit.history()
    pilot = LivePilot.scaled_config()

    assign(socket,
      rows: Stats.monthly(deals, DateTime.utc_now(), hist),
      open_deals: Stats.open(deals),
      recent: Stats.recent(deals, 40),
      deposit: NotionalDeposit.current(),
      history: Enum.reverse(hist),
      pilot: pilot,
      pilot_pct: pilot[:notional_usd] / pilot[:deposit_usd] * 100,
      sync: Sync.status()
    )
  end

  @impl true
  def handle_event("set_deposit", %{"usd" => raw}, socket) do
    case Float.parse(String.trim(raw)) do
      {usd, ""} when usd > 0 ->
        {:ok, usd} = NotionalDeposit.put(usd)
        {:noreply, socket |> assign(flash_msg: "Notional deposit set to $#{money(usd)} from this month on.") |> load()}

      _ ->
        {:noreply, assign(socket, flash_msg: "Not a positive number: #{raw}")}
    end
  end

  def handle_event("refresh", _, socket) do
    Sync.refresh()
    {:noreply, assign(socket, refreshing: true)}
  end

  @impl true
  def handle_info({:account_synced, _}, socket), do: {:noreply, socket |> assign(refreshing: false) |> load()}
  def handle_info(_, socket), do: {:noreply, socket}

  @card "background:#1a1a2e;border-radius:8px;padding:20px 24px;margin-bottom:24px;"
  @th "text-align:right;padding:6px 10px;color:#888;font-weight:normal;font-size:13px;border-bottom:1px solid #333;"
  @thl "text-align:left;padding:6px 10px;color:#888;font-weight:normal;font-size:13px;border-bottom:1px solid #333;"
  @td "text-align:right;padding:6px 10px;font-variant-numeric:tabular-nums;"
  @tdl "text-align:left;padding:6px 10px;"

  @impl true
  def render(assigns) do
    assigns = assign(assigns, card: @card, th: @th, thl: @thl, td: @td, tdl: @tdl)

    ~H"""
    <div style="max-width:1100px;">
      <div style="display:flex;align-items:center;gap:16px;margin-bottom:20px;flex-wrap:wrap;">
        <h1 style="color:#e94560;margin:0;">Account</h1>
        <span style="color:#888;font-size:13px;">
          <%= sync_text(@sync) %>
        </span>
        <button type="button" phx-click="refresh" disabled={@refreshing}
          style="margin-left:auto;background:#0f3460;color:white;border:none;padding:8px 16px;border-radius:6px;cursor:pointer;">
          <%= if @refreshing, do: "Syncing…", else: "Refresh from Binance" %>
        </button>
      </div>

      <div :if={@flash_msg} style="background:#16213e;padding:12px;border-radius:6px;margin-bottom:16px;border-left:4px solid #2ecc71;">
        <%= @flash_msg %>
      </div>

      <div :if={@sync[:mismatches] not in [nil, []]} style="background:#3a1a1a;padding:12px;border-radius:6px;margin-bottom:16px;border-left:4px solid #e74c3c;">
        Positions on Binance don't match the deals rebuilt from fills (history may not reach the opening fill):
        <%= for m <- @sync.mismatches do %>
          <span style="margin-left:8px;"><%= m.symbol %>: exchange <%= m.exchange %>, rebuilt <%= m.rebuilt %></span>
        <% end %>
      </div>

      <div style={@card}>
        <h2 style="margin:0 0 12px;">Notional deposit</h2>
        <div style="display:flex;gap:32px;flex-wrap:wrap;align-items:flex-end;">
          <div>
            <div style="color:#888;font-size:13px;">In force this month</div>
            <div style="font-size:28px;font-weight:bold;">$<%= money(@deposit) %></div>
          </div>
          <form phx-submit="set_deposit" style="display:flex;gap:8px;align-items:center;">
            <input type="number" name="usd" step="any" min="1" value={@deposit} required
              style="width:140px;background:#0f0f23;border:1px solid #333;color:white;padding:8px 12px;border-radius:4px;" />
            <button type="submit" style="background:#533483;color:white;border:none;padding:8px 16px;border-radius:4px;cursor:pointer;">
              Set
            </button>
          </form>
          <div style="color:#aaa;font-size:13px;line-height:1.6;">
            Bot sizing from it: <strong>$<%= money(@pilot[:notional_usd]) %></strong> a trade
            (<%= pct(@pilot_pct) %>), daily brake $<%= money(@pilot[:daily_loss_usd]) %>,
            total kill $<%= money(@pilot[:max_total_loss_usd]) %>.
          </div>
        </div>
        <p style="color:#888;font-size:12px;margin:12px 0 0;">
          A change applies to the whole current month and every later month; earlier months keep the deposit they had.
          <%= if @history != [] do %>
            History:
            <%= for h <- @history do %>
              <span style="margin-right:10px;">from <%= h["from"] %> $<%= money(h["usd"]) %></span>
            <% end %>
          <% else %>
            Not set yet — this is LIVE_PILOT_CAPITAL_USD.
          <% end %>
        </p>
      </div>

      <div style={@card}>
        <h2 style="margin:0 0 4px;">Closed deals by month</h2>
        <p style="color:#888;font-size:12px;margin:0 0 12px;">
          Net = Binance realized PnL − fees + funding, booked in the month the deal closes.
          Bot from <%= Calendar.strftime(Stats.bot_since(), "%Y-%m-%d") %>; manual from deals open on
          <%= Calendar.strftime(Stats.manual_since(), "%Y-%m-%d") %>.
        </p>
        <table style="width:100%;border-collapse:collapse;font-size:14px;">
          <thead>
            <tr>
              <th style={@thl}>Month</th>
              <th style={@thl}>Who</th>
              <th style={@th}>Deals</th>
              <th style={@th}>Won</th>
              <th style={@th}>PnL $</th>
              <th style={@th}>Fees $</th>
              <th style={@th}>Funding $</th>
              <th style={@th}>Net $</th>
              <th style={@th}>Deposit $</th>
              <th style={@th}>Result</th>
            </tr>
          </thead>
          <tbody>
            <%= for r <- @rows do %>
              <tr style={"border-bottom:1px solid #{if r.owner == :manual, do: "#333", else: "#222"};"}>
                <td style={@tdl}><%= if r.owner == :bot, do: r.month %></td>
                <td style={@tdl}><%= owner(r.owner) %></td>
                <td style={@td}><%= r.deals %></td>
                <td style={@td}><%= r.wins %></td>
                <td style={@td}><%= signed(r.pnl_usd) %></td>
                <td style={@td}><%= signed(-r.fees_usd) %></td>
                <td style={@td}><%= signed(r.funding_usd) %></td>
                <td style={@td <> "font-weight:bold;"}><%= signed(r.net_usd) %></td>
                <td style={@td <> "color:#888;"}><%= money(r.deposit_usd) %></td>
                <td style={@td <> "font-weight:bold;color:#{color(r.result_pct)};"}><%= signed_pct(r.result_pct) %></td>
              </tr>
            <% end %>
          </tbody>
        </table>
      </div>

      <div style={@card}>
        <h2 style="margin:0 0 12px;">Open deals</h2>
        <p :if={@open_deals == []} style="color:#888;margin:0;">None.</p>
        <table :if={@open_deals != []} style="width:100%;border-collapse:collapse;font-size:14px;">
          <thead>
            <tr>
              <th style={@thl}>Symbol</th>
              <th style={@thl}>Who</th>
              <th style={@thl}>Side</th>
              <th style={@th}>Qty</th>
              <th style={@thl}>Opened (UTC)</th>
              <th style={@th}>Realized so far $</th>
            </tr>
          </thead>
          <tbody>
            <%= for d <- @open_deals do %>
              <tr>
                <td style={@tdl}><%= d.symbol %></td>
                <td style={@tdl}><%= owner(d.owner) %></td>
                <td style={@tdl}><%= side(d.side) %></td>
                <td style={@td}><%= fmt_qty(abs(d.qty)) %></td>
                <td style={@tdl}><%= ts(d.opened_at) %></td>
                <td style={@td}><%= signed(d.pnl - d.fees + d.funding) %></td>
              </tr>
            <% end %>
          </tbody>
        </table>
      </div>

      <div style={@card}>
        <h2 style="margin:0 0 12px;">Counted closed deals</h2>
        <p :if={@recent == []} style="color:#888;margin:0;">None yet.</p>
        <table :if={@recent != []} style="width:100%;border-collapse:collapse;font-size:14px;">
          <thead>
            <tr>
              <th style={@thl}>Closed (UTC)</th>
              <th style={@thl}>Symbol</th>
              <th style={@thl}>Who</th>
              <th style={@thl}>Side</th>
              <th style={@th}>Max qty</th>
              <th style={@th}>PnL $</th>
              <th style={@th}>Fees $</th>
              <th style={@th}>Funding $</th>
              <th style={@th}>Net $</th>
            </tr>
          </thead>
          <tbody>
            <%= for d <- @recent do %>
              <tr>
                <td style={@tdl}><%= ts(d.closed_at) %></td>
                <td style={@tdl}><%= d.symbol %></td>
                <td style={@tdl}><%= owner(d.owner) %></td>
                <td style={@tdl}><%= side(d.side) %></td>
                <td style={@td}><%= fmt_qty(d.max_qty) %></td>
                <td style={@td}><%= signed(d.pnl) %></td>
                <td style={@td}><%= signed(-d.fees) %></td>
                <td style={@td}><%= signed(d.funding) %></td>
                <td style={@td <> "font-weight:bold;color:#{color(d.net)};"}><%= signed(d.net) %></td>
              </tr>
            <% end %>
          </tbody>
        </table>
      </div>
    </div>
    """
  end

  defp owner(:bot), do: "Bot"
  defp owner(:manual), do: "Manual"

  defp side(1), do: "Long"
  defp side(-1), do: "Short"

  defp money(x), do: :erlang.float_to_binary(x * 1.0, decimals: 2)
  defp pct(x), do: :erlang.float_to_binary(x * 1.0, decimals: 1) <> " %"

  defp signed(x) when x > 0.005, do: "+" <> money(x)
  defp signed(x) when x < -0.005, do: money(x)
  defp signed(_), do: "0.00"

  defp signed_pct(x) when x > 0.005, do: "+" <> :erlang.float_to_binary(x, decimals: 2) <> " %"
  defp signed_pct(x) when x < -0.005, do: :erlang.float_to_binary(x, decimals: 2) <> " %"
  defp signed_pct(_), do: "0.00 %"

  defp color(x) when x > 0.005, do: "#2ecc71"
  defp color(x) when x < -0.005, do: "#e74c3c"
  defp color(_), do: "#ccc"

  defp fmt_qty(q) do
    q |> :erlang.float_to_binary(decimals: 6) |> String.trim_trailing("0") |> String.trim_trailing(".")
  end

  defp ts(%DateTime{} = t), do: Calendar.strftime(t, "%Y-%m-%d %H:%M")

  defp sync_text(%{status: :ok, last_ok_at: t}), do: "Synced #{ts(t)} UTC"
  defp sync_text(%{status: :pending}), do: "First sync within 30 s of app start"
  defp sync_text(%{status: :error, last_error: e}), do: "Last sync failed: #{e}"
  defp sync_text(%{status: :missing_credentials}), do: "No Binance key — not syncing"
  defp sync_text(%{status: :testnet}), do: "Testnet — not syncing"
  defp sync_text(_), do: "Sync worker not running"
end
