import Config

config :fluxtrader, FluxTrader.Repo, pool_size: 10

config :fluxtrader, ecto_repos: [FluxTrader.Repo]

config :fluxtrader, :trading,
  mode: "simulation",
  # One slot per served pair, not 3. M3-2 searched the concurrency cap over 36
  # configurations and `max_concurrent=3` was worse than its uncapped twin in EVERY one, on
  # both pooled and worst-window net: the cap does not select trades, it drops whichever
  # arrive while three are open. Held serially per pair, one slot per pair is a portfolio,
  # not leverage. See docs/M3_2_RESULTS.md §B pattern 3 and Trading.RiskManager.
  #
  # 🔴 This MUST track `served_pairs`. T6 re-tuned the cap over the pre-registered ladder on
  # both universes and `max_concurrent=none` won on both; every cap it tried cost net bps.
  # On twelve pairs a cap of 8 is no longer "one slot per pair" — it is the binding cap T6
  # measured at +13.21 net bps against +19.51 uncapped. Widening the universe without
  # widening this silently re-imposes the constraint T6 said not to use.
  max_positions: 12,
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
  # The pairs the POLICY may rank and trade over — all twelve, from 2026-08-29.
  #
  # T6 did NOT find twelve worse. Its verdict is "UNDECIDED — the incumbent 8-pair universe
  # stands by default": the cleanly-separated universe effect is -2.51 bps with a 95%
  # interval of [-17.85, +12.83], on a period that cannot resolve anything under +/-37 bps.
  # Eight was the conservative default while the four extras had no measured crossing cost;
  # they have one now (`Trading.ExecCost`), so the default no longer has a reason to hold.
  # The standing intent is twelve for the long run, and it is written here rather than left
  # to be re-derived from a results file that reads like a closed decision.
  #
  # 🔴 This is still NOT the collector's pair list, even though the two now coincide. The
  # collector follows `Settings.get_whitelist/0` and must stay free to be WIDER: collecting a
  # pair is cheap and NOT collecting it is unrecoverable, because order-book history begins
  # the day the collector is pointed at a pair and never backfills. Narrowing the whitelist
  # to match this list stops collection and leaves a permanent hole — that is not
  # hypothetical, it happened on 2026-08-28. See PolicyEngine's moduledoc.
  #
  # 🔴 Changing this list changes the RULE, because the top-2% cut is a rank over whatever
  # population is recorded. Do not edit it while a forward test is accumulating trades; the
  # A/B would then span two different policies.
  served_pairs: [
    "BTCUSDT",
    "ETHUSDT",
    "SOLUSDT",
    "DOGEUSDT",
    "WLDUSDT",
    "HYPEUSDT",
    "ZECUSDT",
    "1000PEPEUSDT",
    "XRPUSDT",
    "LINKUSDT",
    "AVAXUSDT",
    "ADAUSDT"
  ],
  # The collector's default subscription list, used ONLY when the DB holds no whitelist row.
  #
  # 🔴 It must never be narrower than what is actually being collected. If this row is ever
  # lost, this list is what the collector falls back to, and any pair missing from it stops
  # being collected with no way to backfill the gap. (`Settings.@default_pairs` is the next
  # fallback down and holds only three.) It listed eight while the VM collected twelve, which
  # was one lost row away from silently dropping XRP, LINK, AVAX and ADA.
  whitelist_pairs: [
    "BTCUSDT",
    "ETHUSDT",
    "SOLUSDT",
    "DOGEUSDT",
    "WLDUSDT",
    "HYPEUSDT",
    "ZECUSDT",
    "1000PEPEUSDT",
    "XRPUSDT",
    "LINKUSDT",
    "AVAXUSDT",
    "ADAUSDT"
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
