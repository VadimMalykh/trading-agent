import Config

config :fluxtrader, FluxTrader.Repo,
  username: "fluxtrader",
  password: "secret",
  hostname: System.get_env("POSTGRES_HOST", "postgres"),
  database: "fluxtrader_test#{System.get_env("MIX_TEST_PARTITION")}",
  pool: Ecto.Adapters.SQL.Sandbox,
  pool_size: 10

# Nothing that talks to Binance, to the inference service, or to the exchange starts under
# `mix test`. Tests that need a worker start it themselves, so a test run can never place a
# paper trade off live market data.
config :fluxtrader, start_workers: false

config :fluxtrader_web, FluxTraderWeb.Endpoint,
  http: [ip: {127, 0, 0, 1}, port: 4002],
  secret_key_base: "test-only-secret-key-base-that-is-at-least-64-bytes-long-for-phoenix-ok",
  server: false

config :logger, level: :warning

config :phoenix, :plug_init_mode, :runtime
