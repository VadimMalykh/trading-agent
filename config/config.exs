import Config

config :fluxtrader, FluxTrader.Repo,
  pool_size: 10

config :fluxtrader, ecto_repos: [FluxTrader.Repo]

config :fluxtrader, :trading,
  mode: "simulation",
  max_positions: 3,
  max_position_pct: 0.10,
  stop_loss_pct: 0.02,
  take_profit_ratio: 2.0,
  leverage: 5,
  whitelist_pairs: ["BTCUSDT", "ETHUSDT", "SOLUSDT"]

config :fluxtrader_web, FluxTraderWeb.Endpoint,
  url: [host: "localhost"],
  adapter: Bandit.PhoenixAdapter,
  render_errors: [
    formats: [html: FluxTraderWeb.ErrorHTML, json: FluxTraderWeb.ErrorJSON],
    layout: false
  ],
  pubsub_server: FluxTraderWeb.PubSub,
  live_view: [signing_salt: "fluxtrader"]

config :logger, :console,
  format: "$time $metadata[$level] $message\n",
  metadata: [:request_id]

config :phoenix, :json_library, Jason

import_config "#{config_env()}.exs"
