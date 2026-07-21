defmodule FluxTrader.Settings.Entry do
  use Ecto.Schema
  import Ecto.Changeset

  @primary_key {:key, :string, autogenerate: false}
  schema "app_settings" do
    field :value, :map
    timestamps(type: :utc_datetime_usec)
  end

  def changeset(entry, attrs) do
    entry
    |> cast(attrs, [:key, :value])
    |> validate_required([:key, :value])
  end
end
