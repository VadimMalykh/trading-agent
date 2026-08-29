defmodule FluxTraderWeb.DashboardLive do
  @moduledoc """
  Dashboard: candles, M2 signals, positions.
  """
  use FluxTraderWeb, :live_view
  require Logger

  @refresh_ms 15_000

  # The M3 block is deliberately NOT on the 15s timer. `Ledger.ab_summary/0` and
  # `Ledger.liveness/0` are Postgres aggregations over the whole bar log and paper ledger,
  # and on the 15s loop they would run four times a minute *per connected browser* against
  # the same small VM that runs the collector and the policy. The underlying data moves on a
  # five-minute bar, so a minute is already faster than the source.
  @m3_refresh_ms 60_000

  @impl true
  def mount(_params, _session, socket) do
    if connected?(socket) do
      Logger.info("DashboardLive mounted (connected) — subscribing to PubSub")
      Phoenix.PubSub.subscribe(FluxTrader.PubSub, "candles:live")
      Phoenix.PubSub.subscribe(FluxTrader.PubSub, "signals:live")
      Process.send_after(self(), :refresh_candles, @refresh_ms)
      Process.send_after(self(), :refresh_m3, @m3_refresh_ms)
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
       m3: fetch_m3(nil),
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

  def handle_info(:refresh_m3, socket) do
    # Reschedule first, before any work, so a Postgres timeout cannot kill the loop forever.
    Process.send_after(self(), :refresh_m3, @m3_refresh_ms)
    {:noreply, assign(socket, m3: fetch_m3(socket.assigns[:m3]))}
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
      <div style="background:#1a1a2e;border-radius:8px;padding:20px;grid-column:1/-1;border:1px solid #533483;">
        <div style="display:flex;justify-content:space-between;align-items:baseline;gap:16px;flex-wrap:wrap;margin-bottom:16px;">
          <h2 style="color:#e94560;margin:0;">M3 Policy — forward paper test</h2>
          <span style="color:#666;font-size:12px;">read-only · refreshed every 60s</span>
        </div>

        <div style="display:flex;gap:12px;flex-wrap:wrap;">
          <.status_badge label="Policy" value={policy_state(@m3)} color={policy_state_color(@m3)} />
          <.status_badge label="Rank window" value={rank_window_label(@m3)} color={rank_window_color(@m3)} />
          <.status_badge label="Rule" value={@m3.rule} color="#533483" />
          <.status_badge label="Universe" value={universe_label(@m3)} color={universe_color(@m3)} />
          <.status_badge label="Last bar" value={ago_badge(@m3, :seconds_since_last_bar)} color={last_bar_color(@m3)} />
          <.status_badge label="Last gated" value={ago_badge(@m3, :seconds_since_last_gated)} color="#533483" />
        </div>

        <p style="color:#cfd3e1;font-size:14px;line-height:1.6;margin-top:16px;margin-bottom:0;">
          <%= explainer(@m3) %>
        </p>

        <%= if universe_drift?(@m3) do %>
          <p style="color:#e74c3c;font-size:13px;line-height:1.6;margin-top:8px;margin-bottom:0;">
            <%= universe_drift_text(@m3) %>
          </p>
        <% end %>

        <%= if @m3.stale do %>
          <p style="color:#f39c12;font-size:12px;margin-top:8px;margin-bottom:0;">
            Ledger unreadable on the last refresh — the warm state and A/B below are the last
            good values, not current ones.
          </p>
        <% end %>

        <h3 style="color:#888;font-size:13px;font-weight:normal;letter-spacing:0.08em;text-transform:uppercase;margin:24px 0 8px;">
          A/B arms (paper)
        </h3>
        <%= if @m3.ab in [nil, []] do %>
          <p style="color:#666;">
            Paper ledger unavailable — the two arms cannot be read from the database right now.
          </p>
        <% else %>
          <div style="overflow-x:auto;">
            <table style="width:100%;border-collapse:collapse;font-size:13px;">
              <thead>
                <tr style="color:#888;text-align:right;">
                  <th style="text-align:left;padding:6px 10px;font-weight:normal;">arm</th>
                  <th style="padding:6px 10px;font-weight:normal;">trades</th>
                  <th style="padding:6px 10px;font-weight:normal;">trades/day</th>
                  <th style="padding:6px 10px;font-weight:normal;">net bps</th>
                  <th style="padding:6px 10px;font-weight:normal;">gross bps</th>
                  <th style="padding:6px 10px;font-weight:normal;">win rate</th>
                  <th style="padding:6px 10px;font-weight:normal;">cum net bps</th>
                  <th style="padding:6px 10px;font-weight:normal;">max drawdown</th>
                  <th style="padding:6px 10px;font-weight:normal;">open</th>
                </tr>
              </thead>
              <tbody>
                <%= for arm <- @m3.ab do %>
                  <tr style="border-top:1px solid #0f0f23;text-align:right;">
                    <td style="text-align:left;padding:8px 10px;"><strong><%= arm[:arm] %></strong></td>
                    <td style="padding:8px 10px;"><%= arm[:trades] %></td>
                    <td style="padding:8px 10px;"><%= metric(arm, arm[:trades_per_day], 2) %></td>
                    <td style={"padding:8px 10px;color:#{metric_color(arm, arm[:net_bps])};"}>
                      <%= metric(arm, arm[:net_bps], 2) %>
                    </td>
                    <td style="padding:8px 10px;"><%= metric(arm, arm[:gross_bps], 2) %></td>
                    <td style="padding:8px 10px;"><%= metric_pct(arm, arm[:win_rate]) %></td>
                    <td style={"padding:8px 10px;color:#{metric_color(arm, arm[:cum_net_bps])};"}>
                      <%= metric(arm, arm[:cum_net_bps], 2) %>
                    </td>
                    <td style="padding:8px 10px;"><%= metric(arm, arm[:max_drawdown_bps], 2) %></td>
                    <td style="padding:8px 10px;"><%= arm[:open] %></td>
                  </tr>
                <% end %>
              </tbody>
            </table>
          </div>
          <p style="color:#666;font-size:12px;margin-top:8px;margin-bottom:0;">
            charged M3-4 measured per-pair crossing cost (pooled <%= @m3.pooled_bps %> bps)
            · <span style="color:#f39c12;">fee tier UNVERIFIED</span>
            · <span style="color:#888;">a dash means not measured yet, not zero</span>
          </p>
        <% end %>

        <h3 style="color:#888;font-size:13px;font-weight:normal;letter-spacing:0.08em;text-transform:uppercase;margin:24px 0 8px;">
          Skips &amp; risk rejections (since boot)
        </h3>
        <%= if @m3.skips == [] and @m3.risk_rejections == [] do %>
          <p style="color:#666;">no skips recorded</p>
        <% else %>
          <div style="display:flex;gap:8px;flex-wrap:wrap;">
            <%= for {reason, count} <- @m3.skips do %>
              <span style={"background:#{chip_color(reason)}22;border:1px solid #{chip_color(reason)};color:#{chip_color(reason)};padding:4px 12px;border-radius:20px;font-size:12px;"}>
                <%= reason %> <strong><%= count %></strong>
              </span>
            <% end %>
            <%= for {reason, count} <- @m3.risk_rejections do %>
              <span style="background:#f39c1222;border:1px solid #f39c12;color:#f39c12;padding:4px 12px;border-radius:20px;font-size:12px;">
                risk: <%= reason %> <strong><%= count %></strong>
              </span>
            <% end %>
          </div>
        <% end %>
        <%= if not_served_count(@m3) > 0 do %>
          <p style="color:#e74c3c;font-size:13px;line-height:1.6;margin-top:10px;margin-bottom:0;">
            <%= not_served_text(@m3) %>
          </p>
        <% end %>
      </div>

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

  # ------------------------------------------------------------------ the M3 panel
  #
  # Everything here is READ-ONLY and calls the trading modules directly rather than fetching
  # `/api/health` over HTTP: `HealthController` is a thin wrapper over exactly these calls,
  # and a second network hop inside the same VM would only add a failure mode. Nothing in
  # `apps/fluxtrader/` changes for this panel — every number below already existed.
  #
  # 🔴 The panel's job is to make CORRECT SILENCE legible. The served checkpoint trades the
  # top 2% of bars by confidence, the edge lives in volatile bars, and the market has been
  # calm — so weeks with no trade are the strategy working. A system that has been quiet for
  # two months is indistinguishable from a broken one, so every empty state here says *why*
  # it is empty and *what would change it*. An empty grey box would be worse than no panel.

  defp fetch_m3(prev) do
    policy = safe_policy()

    {liveness, liveness_ok} =
      case safe_liveness() do
        nil -> {(prev && prev.liveness) || %{}, false}
        l -> {l, true}
      end

    {ab, ab_ok} =
      case safe_ab() do
        nil -> {prev && prev.ab, false}
        list -> {list, true}
      end

    collector = safe_collector_pairs() || (prev && prev.collector_pairs) || []
    carried? = map_size(liveness) > 0 or ab not in [nil, []]

    %{
      policy: policy,
      liveness: liveness,
      ab: ab,
      collector_pairs: collector,
      served_pairs: Map.get(policy, :served_pairs) || [],
      rule: rule_label(),
      coverage: FluxTrader.Trading.Policy.coverage(),
      pooled_bps: FluxTrader.Trading.ExecCost.pooled_bps(),
      skips: count_map(Map.get(policy, :skips)),
      risk_rejections: count_map(Map.get(policy, :risk_rejections)),
      stale: not (liveness_ok and ab_ok) and carried?
    }
  end

  # A dashboard that crashes when Postgres blips is a worse regression than a missing panel:
  # this page is what someone opens *because* they think something is wrong. Same shape as
  # safe_candles/0 and safe_engine/0 above — rescue, catch :exit, return a usable fallback.
  defp safe_policy do
    FluxTrader.Trading.PolicyEngine.status()
  rescue
    e ->
      Logger.warning("policy status failed: #{Exception.message(e)}")
      %{ok: false, error: "policy engine error"}
  catch
    :exit, _ -> %{ok: false, error: "policy engine unavailable"}
  end

  defp safe_liveness do
    FluxTrader.Trading.Ledger.liveness()
  rescue
    e ->
      Logger.warning("ledger liveness failed: #{Exception.message(e)}")
      nil
  catch
    :exit, _ -> nil
  end

  defp safe_ab do
    FluxTrader.Trading.Ledger.ab_summary()
  rescue
    e ->
      Logger.warning("ledger ab_summary failed: #{Exception.message(e)}")
      nil
  catch
    :exit, _ -> nil
  end

  defp safe_collector_pairs do
    FluxTrader.Settings.get_whitelist() |> Enum.sort()
  rescue
    _ -> nil
  catch
    :exit, _ -> nil
  end

  defp rule_label do
    cov = :erlang.float_to_binary(FluxTrader.Trading.Policy.coverage() * 1.0, decimals: 2)
    "cov#{cov}_hold#{FluxTrader.Trading.Policy.hold_minutes()}_SIZED"
  end

  defp count_map(nil), do: []
  defp count_map(map) when map == %{}, do: []

  defp count_map(map) when is_map(map) do
    map
    |> Enum.map(fn {reason, count} -> {to_string(reason), count} end)
    |> Enum.sort_by(fn {reason, count} -> {-count, reason} end)
  end

  defp count_map(_), do: []

  # `warm` is only present when the engine actually answered; the guard fallbacks above carry
  # `ok: false` and no `warm`, so its absence — not `warm: false` — is what "down" means.
  defp policy_up?(m3), do: Map.has_key?(m3.policy, :warm)

  defp policy_state(m3) do
    cond do
      not policy_up?(m3) -> "down"
      m3.policy[:warm] == true -> "warm"
      true -> "warming"
    end
  end

  defp policy_state_color(m3) do
    case policy_state(m3) do
      "warm" -> "#2ecc71"
      "warming" -> "#f39c12"
      _ -> "#e74c3c"
    end
  end

  defp rank_bars(m3), do: m3.liveness[:bars_in_rank_window] || m3.policy[:rank_window_bars]

  defp rank_needed(m3),
    do: m3.liveness[:min_rank_bars] || FluxTrader.Trading.Ledger.min_rank_bars()

  defp rank_window_label(m3) do
    case rank_bars(m3) do
      nil -> "unknown"
      n -> "#{format_count(n)} / #{format_count(rank_needed(m3))} bars"
    end
  end

  defp rank_window_color(m3) do
    cond do
      is_nil(rank_bars(m3)) -> "#666"
      m3.policy[:warm] == true -> "#2ecc71"
      true -> "#f39c12"
    end
  end

  defp universe_drift?(m3) do
    m3.served_pairs != [] and m3.collector_pairs != [] and
      MapSet.new(m3.served_pairs) != MapSet.new(m3.collector_pairs)
  end

  defp universe_label(m3) do
    if universe_drift?(m3) do
      "#{length(m3.served_pairs)} served / #{length(m3.collector_pairs)} collected"
    else
      "#{length(m3.served_pairs)} served"
    end
  end

  defp universe_color(m3) do
    cond do
      universe_drift?(m3) -> "#e74c3c"
      m3.served_pairs == [] -> "#666"
      true -> "#533483"
    end
  end

  defp universe_drift_text(m3) do
    served = MapSet.new(m3.served_pairs)
    collected = MapSet.new(m3.collector_pairs)
    only_served = MapSet.difference(served, collected) |> Enum.sort() |> Enum.join(", ")
    only_collected = MapSet.difference(collected, served) |> Enum.sort() |> Enum.join(", ")

    "The served universe and the collector whitelist have drifted apart — this is the " <>
      "2026-08-28 production defect. Served but not collected: #{empty_or(only_served)}. " <>
      "Collected but not served: #{empty_or(only_collected)}. Do not fix this by narrowing " <>
      "the collector whitelist: collection gaps never backfill."
  end

  defp empty_or(""), do: "none"
  defp empty_or(s), do: s

  # Never red, per the panel's whole reason for existing: a long silence is the expected
  # state, not a fault.
  defp last_bar_color(m3) do
    case m3.liveness[:seconds_since_last_bar] do
      nil -> "#f39c12"
      s when s < 900 -> "#2ecc71"
      s when s < 3600 -> "#f39c12"
      _ -> "#e74c3c"
    end
  end

  defp explainer(m3) do
    cond do
      not policy_up?(m3) ->
        reason = m3.policy[:error] || m3.policy[:last_error] || "no reason reported"

        "The policy engine is not answering (#{reason}). While it is down no bars are " <>
          "recorded and neither arm can trade — unlike a quiet market, this is a fault."

      map_size(m3.liveness) == 0 ->
        "The policy engine is up, but the bar log cannot be read, so warm state and the " <>
          "A/B below are unknown. The policy keeps its own rank window and is unaffected " <>
          "by this page."

      m3.policy[:warm] != true ->
        bars = rank_bars(m3) || 0
        need = rank_needed(m3)
        pairs = length(m3.served_pairs)

        "Warming up: #{format_count(bars)} / #{format_count(need)} bars. The policy may " <>
          "not trade until the rank window fills — #{warm_eta(need - bars, pairs)}. " <>
          "The window is a bar COUNT pooled across the served pairs" <>
          bars_per_day_clause(pairs) <> ", not a calendar week."

      true ->
        cov = :erlang.float_to_binary(m3.coverage * 100.0, decimals: 0)

        "Warm — the rank window is full and the policy is free to trade. " <>
          gated_sentence(m3) <>
          " Expected: it takes only the top #{cov}% of bars by confidence, the edge lives " <>
          "in volatile bars, and the market has been calm, so weeks with no trade are the " <>
          "strategy working rather than a fault. " <> last_bar_sentence(m3)
    end
  end

  defp bars_per_day_clause(0), do: ""

  defp bars_per_day_clause(pairs),
    do: " (#{pairs} pairs x 288 = #{format_count(pairs * 288)} bars/day)"

  defp warm_eta(remaining, _pairs) when remaining <= 0, do: "it should clear on the next tick"

  defp warm_eta(_remaining, 0),
    do: "the engine reported no served pairs, so the time to fill cannot be estimated"

  defp warm_eta(remaining, pairs) do
    hours = remaining / (288 * pairs) * 24.0

    cond do
      hours < 1 -> "about #{max(round(hours * 60), 1)} more minutes at #{pairs} pairs"
      hours < 48 -> "about #{round(hours)} more hours at #{pairs} pairs"
      true -> "about #{Float.round(hours / 24.0, 1)} more days at #{pairs} pairs"
    end
  end

  defp gated_sentence(m3) do
    case m3.liveness[:seconds_since_last_gated] do
      nil -> "No gated signal has fired yet."
      s -> "No gated signal for #{format_duration(s)}."
    end
  end

  defp last_bar_sentence(m3) do
    case m3.liveness[:seconds_since_last_bar] do
      nil -> "No bar has been recorded yet, which is worth checking: the engine records one per served pair every five minutes once inference is running."
      s -> "Last bar seen #{format_ago(s)}."
    end
  end

  defp not_served_count(m3) do
    case List.keyfind(m3.skips, "not_served", 0) do
      {_, count} -> count
      nil -> 0
    end
  end

  defp not_served_text(m3) do
    "not_served is non-zero (#{not_served_count(m3)}): the policy is seeing bars for pairs " <>
      "it does not serve, which means the served universe and the collector whitelist have " <>
      "drifted apart. BACKLOG names this as the signal that the 2026-08-28 defect has " <>
      "recurred."
  end

  defp chip_color("not_served"), do: "#e74c3c"
  defp chip_color("warming_up"), do: "#f39c12"
  defp chip_color(_), do: "#533483"

  # 🔴 `nil` is not `0.0`. With no trades yet `gross_bps` / `net_bps` / `win_rate` come back
  # nil, and `cum_net_bps` / `max_drawdown_bps` come back a structural 0.0 that means "no
  # trades", not "measured, and it is zero". Both render as an em dash — rendering 0.00 would
  # claim a measurement that has not been taken.
  defp metric(arm, value, decimals) do
    if arm[:trades] in [0, nil] or is_nil(value) do
      "—"
    else
      :erlang.float_to_binary(value * 1.0, decimals: decimals)
    end
  end

  defp metric_pct(arm, value) do
    if arm[:trades] in [0, nil] or is_nil(value) do
      "—"
    else
      "#{:erlang.float_to_binary(value * 100.0, decimals: 1)}%"
    end
  end

  defp metric_color(arm, value) do
    if arm[:trades] in [0, nil] or is_nil(value), do: "#888", else: pnl_color(value)
  end

  defp format_count(n) when is_integer(n) do
    n
    |> Integer.to_string()
    |> String.reverse()
    |> String.replace(~r/(\d{3})(?=\d)/, "\\1,")
    |> String.reverse()
  end

  defp format_count(n), do: to_string(n)

  # "never" is a fact about the ledger; "unknown" is a fact about this page's ability to read
  # it. Rendering the second as the first is the exact class of error this panel exists to
  # avoid — it would report a silence that was never observed.
  defp ago_badge(m3, key) do
    if map_size(m3.liveness) == 0, do: "unknown", else: format_ago(m3.liveness[key])
  end

  defp format_ago(nil), do: "never"
  defp format_ago(seconds), do: "#{format_duration(seconds)} ago"

  defp format_duration(s) when is_integer(s) and s < 60, do: "#{max(s, 0)}s"
  defp format_duration(s) when is_integer(s) and s < 3600, do: "#{div(s, 60)}m"
  defp format_duration(s) when is_integer(s) and s < 86_400, do: "#{div(s, 3600)}h"
  defp format_duration(s) when is_integer(s), do: "#{div(s, 86_400)}d"
  defp format_duration(s), do: to_string(s)

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
