defmodule FluxTrader.Trading.PaperTrade do
  @moduledoc """
  One paper position, on one arm of the A/B. Columns mirror `backtest.py`'s trade frame so
  the live ledger scores with the same arithmetic as the offline one.

  The two arms are `policy` (frozen cut, regime-sized 1/3..5/3) and `flat_size` (the same
  bars, size 1.0). They differ in exactly one dimension by construction — see
  `Policy.decide_flat/3`, which delegates its entry decision to `Policy.decide/3` rather than
  restating it.
  """
  use Ecto.Schema
  import Ecto.Changeset

  # 🔴 The control arm was renamed `signal_only` -> `flat_size` on 2026-08-31, when it was
  # re-registered to mean "the same bars as the policy, at flat size" rather than "every bar
  # M2's gate approves" (see `Policy.decide_flat/3`). The rename is not cosmetic: the old name
  # names an entry condition the arm no longer has, and a stale name on a live column is how a
  # future reader mis-reads a whole results table. Safe to change because `paper_trades` is
  # truncated in the same deploy — no row carries the old value.
  @arms ~w(policy flat_size)

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
    # Provenance (M3_PROTOCOL §9.6): the checkpoint and ladder this row was taken under, so
    # the ledger survives a checkpoint swap instead of being truncated.
    field(:checkpoint, :string)
    field(:ladder_p80, :float)

    timestamps()
  end

  @fields ~w(arm pair side size entry_ts exit_after_ts exit_ts entry_price exit_price quantity notional
             gross_bps cost_bps net_bps status confidence threshold regime checkpoint ladder_p80)a
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
