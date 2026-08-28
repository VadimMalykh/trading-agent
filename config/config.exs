import Config

config :fluxtrader, FluxTrader.Repo, pool_size: 10

config :fluxtrader, ecto_repos: [FluxTrader.Repo]

config :fluxtrader, :trading,
  mode: "simulation",
  # One slot per served pair, not 3. M3-2 searched the concurrency cap over 36
  # configurations and `max_concurrent=3` was worse than its uncapped twin in EVERY one, on
  # both pooled and worst-window net: the cap does not select trades, it drops whichever
  # arrive while three are open. Held serially per pair, 8 slots is a portfolio, not
  # leverage. See docs/M3_2_RESULTS.md §B pattern 3 and Trading.RiskManager.
  max_positions: 8,
  # Base notional per position, before the policy's 1/3..5/3 regime multiplier.
  max_position_pct: 0.10,
  # The hard ceiling that multiplier may not push a position through (5/3 x 0.10 = 0.167).
  max_notional_pct: 0.20,
  max_daily_loss_pct: 0.05,
  max_leverage: 10,
  # NOT a risk limit. The policy owns coverage (M3_PLAN §3.1); a confidence floor here could
  # only narrow what the policy chose, never widen it. Kept as an operator override.
  min_confidence: 0.0,
  stop_loss_pct: 0.02,
  take_profit_ratio: 2.0,
  leverage: 5,
  total_capital: 1000.0,
  # The pairs the POLICY may rank and trade over: the eight M3-2 measured the rule on and
  # M3-4 measured a crossing cost for. T6 closed the 8-vs-12 question, so this is a settled
  # scope, not a placeholder.
  #
  # 🔴 This is NOT the collector's pair list. The collector follows
  # `Settings.get_whitelist/0`, which is deliberately wider — collecting a pair is cheap and
  # NOT collecting it is unrecoverable. Narrowing the whitelist to match this list stops
  # collection and leaves a permanent hole. See PolicyEngine's moduledoc.
  served_pairs: [
    "BTCUSDT",
    "ETHUSDT",
    "SOLUSDT",
    "DOGEUSDT",
    "WLDUSDT",
    "HYPEUSDT",
    "ZECUSDT",
    "1000PEPEUSDT"
  ],
  # The collector's default subscription list, used only when the DB holds no whitelist row.
  whitelist_pairs: [
    "BTCUSDT",
    "ETHUSDT",
    "SOLUSDT",
    "DOGEUSDT",
    "WLDUSDT",
    "HYPEUSDT",
    "ZECUSDT",
    "1000PEPEUSDT"
  ]

config :fluxtrader, :ml,
  inference_url: "http://ml_inference:8001",
  gate_threshold: 0.40

config :fluxtrader, :telegram,
  bot_token: System.get_env("TELEGRAM_BOT_TOKEN"),
  chat_id: System.get_env("TELEGRAM_CHAT_ID")

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
