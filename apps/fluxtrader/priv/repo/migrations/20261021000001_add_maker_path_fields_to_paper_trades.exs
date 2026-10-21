defmodule FluxTrader.Repo.Migrations.AddMakerPathFieldsToPaperTrades do
  @moduledoc """
  M2 (BOOK_WAVE2_PLAN §M2, built 2026-10-21): the pilot arm's maker path records, per leg,
  what was rested, how long, and what it filled at — the fields S2 reads. Nil on every row
  the maker path did not place (paper rows; the pilot's rows before M2).
  """
  use Ecto.Migration

  def change do
    alter table(:paper_trades) do
      # "maker" (rested and filled), "maker_partial" (part filled at the rest, the remainder
      # under the exchange's minimum and left), "maker_then_taker" (unfilled or part filled at
      # W, the remainder crossed), "rejected_then_crossed" (GTX refused: the market had moved
      # through our side; crossed at once), "taker" (the path was off), "maker_resting" (the
      # leg is still resting — a transient state, never on a closed row).
      add :entry_order_type, :string
      add :entry_rest_price, :float
      add :entry_wait_s, :float
      add :entry_fill_price, :float
      # The leg's realised fee in bps of notional (maker 2.0 / taker 5.0 per side, weighted by
      # the filled quantities); cost_bps on a maker-path row is the sum of the two legs'.
      add :entry_fee_bps, :float
      # The touch the rest price was taken from, at the decision tick (the trading host's
      # bookTicker; the collector's own ladder at that instant is the offline reference).
      add :entry_touch_bid, :float
      add :entry_touch_ask, :float
      add :exit_order_type, :string
      add :exit_rest_price, :float
      add :exit_wait_s, :float
      add :exit_fill_price, :float
      add :exit_fee_bps, :float
      add :exit_touch_bid, :float
      add :exit_touch_ask, :float
      # When the exit leg was placed — the exit's t_d for the taker counterfactual (the
      # entry's is inserted_at: the row is written when its entry is placed).
      add :exit_rest_at, :utc_datetime
    end
  end
end
