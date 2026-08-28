defmodule FluxTrader.Trading.PaperTrade do
  @moduledoc """
  One paper position, on one arm of the A/B. Columns mirror `backtest.py`'s trade frame so
  the live ledger scores with the same arithmetic as the offline one.
  """
  use Ecto.Schema
  import Ecto.Changeset

  @arms ~w(policy signal_only)

  schema "paper_trades" do
    field(:arm, :string)
    field(:pair, :string)
    field(:side, :integer)
    field(:size, :float, default: 1.0)
    field(:entry_ts, :utc_datetime)
    field(:exit_after_ts, :utc_datetime)
    field(:exit_ts, :utc_datetime)
    field(:entry_price, :float)
    field(:exit_price, :float)
    field(:quantity, :float)
    field(:notional, :float)
    field(:gross_bps, :float)
    field(:cost_bps, :float)
    field(:net_bps, :float)
    field(:status, :string, default: "open")
    field(:confidence, :float)
    field(:threshold, :float)
    field(:regime, :float)

    timestamps()
  end

  @fields ~w(arm pair side size entry_ts exit_after_ts exit_ts entry_price exit_price quantity notional
             gross_bps cost_bps net_bps status confidence threshold regime)a
  @required ~w(arm pair side size entry_ts exit_after_ts entry_price status)a

  def arms, do: @arms

  def changeset(trade, attrs) do
    trade
    |> cast(attrs, @fields)
    |> validate_required(@required)
    |> validate_inclusion(:arm, @arms)
    |> validate_inclusion(:side, [-1, 1])
    |> validate_inclusion(:status, ~w(open closed))
    |> unique_constraint([:arm, :pair], name: :paper_trades_one_open_per_pair)
  end
end
