defmodule FluxTrader.Repo.Migrations.AddExtensionsToPaperTrades do
  @moduledoc """
  M3_5_INTEGRATION §4.4 (built 2026-11-09, NOT in force until its gate): how many times a
  row's timed exit was pushed forward by 240 minutes because the served model still took
  the trade's side above the explore cut at the exit bar. 0 on every row today; at most 2.
  `exit_reason` on such a row is `ext1_timer` / `ext2_timer`.
  """
  use Ecto.Migration

  def change do
    alter table(:paper_trades) do
      add :extensions, :integer, default: 0, null: false
    end
  end
end
