defmodule FluxTrader.Trading.PolicyBar do
  @moduledoc """
  One (pair, 5-minute bar) observation of the model: what it said, and what the market
  regime was when it said it. See the `create_policy_bars` migration for why this is
  persisted rather than held in memory.
  """
  use Ecto.Schema
  import Ecto.Changeset

  schema "policy_bars" do
    field(:pair, :string)
    field(:bar_ts, :utc_datetime)
    field(:horizon_m, :integer)
    field(:confidence, :float)
    field(:side, :integer)
    field(:price, :float)
    field(:gated, :boolean, default: false)
    field(:regime, :float)

    timestamps(updated_at: false)
  end

  @fields ~w(pair bar_ts horizon_m confidence side price gated regime)a
  @required ~w(pair bar_ts horizon_m confidence side)a

  def changeset(bar, attrs) do
    bar
    |> cast(attrs, @fields)
    |> validate_required(@required)
    |> validate_inclusion(:side, [-1, 0, 1])
    |> unique_constraint([:pair, :bar_ts, :horizon_m])
  end
end
