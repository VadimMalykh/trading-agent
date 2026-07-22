defmodule FluxTraderWeb.Layouts do
  @moduledoc false
  use FluxTraderWeb, :html

  def root(assigns) do
    ~H"""
    <!DOCTYPE html>
    <html lang="en">
      <head>
        <meta charset="utf-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <meta name="csrf-token" content={get_csrf_token()} />
        <title>FluxTrader</title>
        <style>
          :root {
            --bg-primary: #0f0f23;
            --bg-secondary: #1a1a2e;
            --bg-tertiary: #16213e;
            --accent: #e94560;
            --accent-alt: #533483;
            --text-primary: #e0e0e0;
            --text-secondary: #888;
            --green: #2ecc71;
            --red: #e74c3c;
            --blue: #0f3460;
          }
          * { margin: 0; padding: 0; box-sizing: border-box; }
          body {
            background: var(--bg-primary);
            color: var(--text-primary);
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
          }
          a { color: var(--accent); text-decoration: none; }
          a:hover { text-decoration: underline; }
          .phx-disconnected #lv-disconnect-banner { display: block !important; }
          .phx-connected #lv-disconnect-banner { display: none !important; }
        </style>
        <script src="https://cdn.jsdelivr.net/npm/phoenix@1.7.21/priv/static/phoenix.min.js"></script>
        <script src="https://cdn.jsdelivr.net/npm/phoenix_live_view@0.20.17/priv/static/phoenix_live_view.min.js"></script>
      </head>
      <body>
        <div
          id="lv-disconnect-banner"
          style="display:none;position:fixed;top:0;left:0;right:0;z-index:9999;background:#e74c3c;color:#fff;text-align:center;padding:8px 12px;font-size:13px;font-weight:600;"
        >
          Connection lost — reconnecting…
        </div>
        <%= @inner_content %>
        <script>
          (function () {
            var Phoenix = window.Phoenix;
            var LiveView = window.LiveView || window.phoenix_live_view;
            if (!Phoenix || !LiveView) {
              console.error("Phoenix/LiveView JS not loaded from CDN");
              return;
            }

            var LiveSocket = LiveView.LiveSocket || LiveView;
            var Socket = Phoenix.Socket;
            var csrf = document.querySelector("meta[name='csrf-token']");
            var token = csrf ? csrf.getAttribute("content") : "";

            var liveSocket = new LiveSocket("/live", Socket, {
              params: { _csrf_token: token },
              heartbeatIntervalMs: 15000
            });

            liveSocket.connect();
            window.liveSocket = liveSocket;

            function reconnect() {
              if (!liveSocket) return;
              try { liveSocket.disconnect(); } catch (_) {}
              setTimeout(function () { liveSocket.connect(); }, 100);
            }

            document.addEventListener("visibilitychange", function () {
              if (document.visibilityState === "visible" && liveSocket && !liveSocket.isConnected()) {
                reconnect();
              }
            });

            window.addEventListener("online", function () {
              if (liveSocket && !liveSocket.isConnected()) reconnect();
            });

            var disconnectedSince = null;
            setInterval(function () {
              if (!liveSocket) return;
              if (liveSocket.isConnected()) {
                disconnectedSince = null;
                return;
              }
              if (disconnectedSince === null) {
                disconnectedSince = Date.now();
                return;
              }
              if (Date.now() - disconnectedSince >= 60000) {
                console.warn("LiveView disconnected too long; reloading");
                window.location.reload();
              } else {
                reconnect();
              }
            }, 5000);
          })();
        </script>
      </body>
    </html>
    """
  end

  def app(assigns) do
    ~H"""
    <header style="background:#1a1a2e;padding:12px 24px;display:flex;gap:24px;align-items:center;">
      <.link navigate={~p"/"} style="color:#e94560;font-weight:bold;font-size:18px;text-decoration:none;">
        FluxTrader
      </.link>
      <.link navigate={~p"/"} style="color:#ccc;text-decoration:none;">
        Dashboard
      </.link>
      <.link navigate={~p"/settings"} style="color:#ccc;text-decoration:none;">
        Settings
      </.link>
    </header>

    <main style="padding:24px;background:#0f0f23;min-height:calc(100vh - 52px);color:#e0e0e0;">
      <.flash_group flash={@flash} />
      <%= @inner_content %>
    </main>
    """
  end
end
