import Config

if config_env() == :prod do
  database_url =
    System.get_env("DATABASE_URL") ||
      raise """
      environment variable DATABASE_URL is missing.
      For example: ecto://USER:PASS@HOST/DATABASE
      """

  config :fluxtrader, FluxTrader.Repo,
    url: database_url,
    pool_size: String.to_integer(System.get_env("POOL_SIZE") || "10")

  secret_key_base =
    System.get_env("SECRET_KEY_BASE") ||
      raise """
      environment variable SECRET_KEY_BASE is missing.
      You can generate one by calling: mix phx.gen.secret
      """

  host = System.get_env("PHX_HOST") || "example.com"
  port = String.to_integer(System.get_env("PORT") || "4000")

  config :fluxtrader_web, FluxTraderWeb.Endpoint,
    url: [host: host, port: 443, scheme: "https"],
    http: [ip: {0, 0, 0, 0}, port: port],
    secret_key_base: secret_key_base

  config :fluxtrader, :binance,
    api_key: System.get_env("BINANCE_API_KEY"),
    api_secret: System.get_env("BINANCE_API_SECRET")

  config :fluxtrader, :trading,
    mode: System.get_env("TRADING_MODE", "simulation"),
    # Defaults mirror config.exs; see there for why the position cap tracks the served
    # universe and why min_confidence is 0.0.
    max_positions: String.to_integer(System.get_env("MAX_POSITIONS") || "12"),
    max_position_pct: String.to_float(System.get_env("MAX_POSITION_PCT") || "0.10"),
    max_notional_pct: String.to_float(System.get_env("MAX_NOTIONAL_PCT") || "0.20"),
    max_daily_loss_pct: String.to_float(System.get_env("MAX_DAILY_LOSS_PCT") || "0.05"),
    max_leverage: String.to_integer(System.get_env("MAX_LEVERAGE") || "10"),
    min_confidence: String.to_float(System.get_env("MIN_CONFIDENCE") || "0.0"),
    stop_loss_pct: String.to_float(System.get_env("STOP_LOSS_PCT") || "0.02"),
    take_profit_ratio: String.to_float(System.get_env("TAKE_PROFIT_RATIO") || "2.0"),
    leverage: String.to_integer(System.get_env("LEVERAGE") || "5"),
    total_capital: String.to_float(System.get_env("TOTAL_CAPITAL") || "1000.0"),
    # See config.exs: this fallback must never be narrower than what is actually collected.
    whitelist_pairs:
      System.get_env(
        "WHITELIST_PAIRS",
        "BTCUSDT,ETHUSDT,SOLUSDT,DOGEUSDT,WLDUSDT,HYPEUSDT,ZECUSDT,1000PEPEUSDT," <>
          "XRPUSDT,LINKUSDT,AVAXUSDT,ADAUSDT"
      )
      |> String.split(",", trim: true)
end

# Ecto query logging — every environment, resolved at boot rather than at compile time so
# the always-on VM can flip it with an env var and a restart.
#
# Ecto logs EVERY query at :debug with its parameters interpolated. The collector writes
# ~2.4 rows/s across twelve pairs and `orderbook_levels` carries all 100 book levels in its
# parameters, so on 2026-09-05 this alone produced a 1.1 GB container log in 25 hours. It is
# off by default: the per-insert stream has no diagnostic value on a running collector, and
# a FAILING query still raises and is logged by the caller, so nothing about errors is lost.
#
# Set ECTO_LOG_LEVEL=debug for a local debugging session where you want to see the SQL.
# An unrecognised value falls back to `false` rather than raising: this runs at boot on the
# always-on collector, and a typo in an env var must not be able to take data collection
# down. The warning is the signal that it was ignored.
ecto_log =
  case System.get_env("ECTO_LOG_LEVEL", "false") do
    "false" -> false
    level when level in ~w(debug info notice warning error) -> String.to_existing_atom(level)
    other ->
      IO.warn("ignoring ECTO_LOG_LEVEL=#{inspect(other)}; query logging stays off")
      false
  end

config :fluxtrader, FluxTrader.Repo, log: ecto_log
