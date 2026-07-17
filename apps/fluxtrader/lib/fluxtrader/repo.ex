defmodule FluxTrader.Repo do
  use Ecto.Repo,
    otp_app: :fluxtrader,
    adapter: Ecto.Adapters.Postgres
end
