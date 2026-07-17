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
    max_positions: String.to_integer(System.get_env("MAX_POSITIONS") || "3"),
    max_position_pct: String.to_float(System.get_env("MAX_POSITION_PCT") || "0.10"),
    stop_loss_pct: String.to_float(System.get_env("STOP_LOSS_PCT") || "0.02"),
    take_profit_ratio: String.to_float(System.get_env("TAKE_PROFIT_RATIO") || "2.0"),
    leverage: String.to_integer(System.get_env("LEVERAGE") || "5"),
    whitelist_pairs:
      System.get_env("WHITELIST_PAIRS", "BTCUSDT,ETHUSDT,SOLUSDT")
      |> String.split(",", trim: true)
end
