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
        <link rel="stylesheet" href={~p"/assets/app.css"} />
        <script defer src="https://cdn.jsdelivr.net/npm/phoenix@1.7.21/priv/static/phoenix.min.js"></script>
        <script defer src="https://cdn.jsdelivr.net/npm/phoenix_live_view@0.20.17/priv/static/phoenix_live_view.min.js"></script>
        <script defer phx-track-static type="text/javascript" src={~p"/assets/app.js"}></script>
      </head>
      <body>
        <div
          id="lv-disconnect-banner"
          style="display:none;position:fixed;top:0;left:0;right:0;z-index:9999;background:#e74c3c;color:#fff;text-align:center;padding:8px 12px;font-size:13px;font-weight:600;"
        >
          Connection lost — reconnecting…
        </div>
        <style>
          .phx-disconnected #lv-disconnect-banner { display: block !important; }
          .phx-connected #lv-disconnect-banner { display: none !important; }
        </style>
        <%= @inner_content %>
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
