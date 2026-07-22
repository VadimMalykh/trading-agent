defmodule FluxTraderWeb.Endpoint do
  use Phoenix.Endpoint, otp_app: :fluxtrader_web

  @session_options [
    store: :cookie,
    key: "_fluxtrader_web_key",
    signing_salt: "fluxtrader",
    same_site: "Lax"
  ]

  socket "/live", Phoenix.LiveView.Socket,
    websocket: [
      connect_info: [session: @session_options],
      # Drop idle/dead sockets after missed heartbeats (client heartbeats every 15s)
      timeout: 60_000
    ],
    longpoll: [connect_info: [session: @session_options]]

  plug Plug.Static,
    at: "/",
    from: :fluxtrader_web,
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
