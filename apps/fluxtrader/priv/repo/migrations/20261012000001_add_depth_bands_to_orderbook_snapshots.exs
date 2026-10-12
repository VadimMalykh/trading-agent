defmodule FluxTrader.Repo.Migrations.AddDepthBandsToOrderbookSnapshots do
  @moduledoc """
  BOOK_WAVE2_PLAN §L1 / Vadim's option 2 (2026-10-12): the archive-style depth bands, computed
  live by the collector over the whole fetched ladder (poll depth raised 100 -> 500), so a
  feature trained on Binance's public bookDepth history (30 s, from 2024-05) can be served
  from the same quantity. NULL on every row before this migration — their bands were never
  computed, and the 100-level ladder of that era does not reach them on the majors.
  """
  use Ecto.Migration

  def change do
    alter table(:orderbook_snapshots) do
      add :bid_band_0_2, :float
      add :ask_band_0_2, :float
      add :bid_band_1, :float
      add :ask_band_1, :float
      add :bid_band_2, :float
      add :ask_band_2, :float
      add :bid_band_3, :float
      add :ask_band_3, :float
      add :bid_band_4, :float
      add :ask_band_4, :float
      add :bid_band_5, :float
      add :ask_band_5, :float
      add :bid_reach_bps, :float
      add :ask_reach_bps, :float
      add :depth_fetched, :integer
    end
  end
end
