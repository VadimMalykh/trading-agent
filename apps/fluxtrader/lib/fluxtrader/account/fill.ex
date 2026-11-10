defmodule FluxTrader.Account.Fill do
  @moduledoc "One exchange fill on the shared account, as `/fapi/v1/userTrades` reports it."
  use Ecto.Schema

  schema "account_fills" do
    field(:symbol, :string)
    field(:trade_id, :integer)
    field(:order_id, :integer)
    field(:side, :string)
    field(:qty, :float)
    field(:price, :float)
    field(:realized_pnl, :float)
    field(:commission, :float)
    field(:commission_asset, :string)
    field(:maker, :boolean)
    field(:time, :utc_datetime_usec)
    timestamps()
  end
end

defmodule FluxTrader.Account.Income do
  @moduledoc "One `/fapi/v1/income` row. Only `FUNDING_FEE` enters a deal; the rest are kept for audit."
  use Ecto.Schema

  schema "account_income" do
    field(:symbol, :string)
    field(:income_type, :string)
    field(:income, :float)
    field(:asset, :string)
    field(:tran_id, :integer)
    field(:trade_id, :string)
    field(:time, :utc_datetime_usec)
    timestamps()
  end
end
