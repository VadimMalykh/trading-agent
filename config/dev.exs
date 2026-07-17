import Config

config :fluxtrader, FluxTrader.Repo,
  username: "fluxtrader",
  password: "secret",
  hostname: "postgres",
  database: "fluxtrader",
  stacktrace: true,
  show_sensitive_data_on_connection_error: true,
  pool_size: 10

config :fluxtrader_web, FluxTraderWeb.Endpoint,
  http: [ip: {0, 0, 0, 0}, port: 4000],
  check_origin: false,
  code_reloader: true,
  debug_errors: true,
  secret_key_base: "dev-only-secret-key-base-that-is-at-least-64-bytes-long-for-phoenix-to-start",
  watchers: []

config :logger, :console, format: "[$level] $message\n"

config :phoenix, :stacktrace_depth, 20
config :phoenix, :plug_init_mode, :runtime
