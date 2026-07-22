defmodule FluxTraderWeb.Endpoint do
  use Phoenix.Endpoint, otp_app: :fluxtrader_web

  @session_options [
    store: :cookie,
    key: "_fluxtrader_web_key",
    signing_salt: "fluxtrader",
    same_site: "Lax"
  ]

  # Serve from source priv/static (bind-mounted), not _build volume copy.
  # Named volume app_build can lag or miss priv files after host edits.
  @static_root Path.expand("../../priv/static", __DIR__)

  socket "/live", Phoenix.LiveView.Socket,
    websocket: [
      connect_info: [session: @session_options],
      timeout: 60_000
    ],
    longpoll: [connect_info: [session: @session_options]]

  plug Plug.Static,
    at: "/",
    from: @static_root,
    gzip: false,
    only: ~w(assets fonts images favicon.ico robots.txt)

  if code_reloading? do
    socket "/phoenix/live_reload/socket", Phoenix.LiveReloader.Socket
    plug Phoenix.LiveReloader
    plug Phoenix.CodeReloader
  end

  plug Plug.RequestId
  plug Plug.Telemetry, event_prefix: [:phoenix, :endpoint]

  plug Plug.Parsers,
    parsers: [:urlencoded, :multipart, :json],
    pass: ["*/*"],
    json_decoder: Phoenix.json_library()

  plug Plug.MethodOverride
  plug Plug.Head
  plug Plug.Session, @session_options
  plug FluxTraderWeb.Router
end
