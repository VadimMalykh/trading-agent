defmodule FluxTrader.MarketData.OpenInterest do
  use Ecto.Schema
  import Ecto.Changeset

  @primary_key false
  schema "open_interest" do
    field :symbol, :string
    field :ts, :utc_datetime_usec
    # Exchange "time" from /fapi/v1/openInterest; NULL before migration
    # 20260824000001. `ts` stays local collection time. See B4.1.
    field :event_time, :utc_datetime_usec
    field :open_interest, :float
  end

  def changeset(row, attrs) do
    row
    |> cast(attrs, [:symbol, :ts, :event_time, :open_interest])
    |> validate_required([:symbol, :ts, :open_interest])
  end
end
