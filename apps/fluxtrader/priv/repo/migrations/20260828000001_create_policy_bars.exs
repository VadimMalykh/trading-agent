defmodule FluxTrader.Repo.Migrations.CreatePolicyBars do
  @moduledoc """
  The bar log the M3 policy ranks against (M3_PLAN §2 M3-5 item 1).

  Entry is by **coverage rank**, not by a confidence constant, so the policy needs a
  population of recent bars to take the top 2% of. Keeping that population in memory would
  mean a redeploy costs the whole warmup — and unlike the regime observable, model
  confidences cannot be re-derived from the exchange after the fact. So it is a table.

  It is also the raw evidence of the forward paper test. §0.5.4's binding constraint is that
  253 days holding ~220 independent ones cannot certify a 15-bps edge and no re-analysis of
  them can; only forward time produces new independent days. This table is where those days
  accumulate.
  """
  use Ecto.Migration

  def change do
    create table(:policy_bars) do
      add :pair, :string, null: false
      # Floored onto the 5-minute grid the model is scored on. The signal engine polls every
      # 30s; without flooring, one bar would enter the ranking population ten times.
      add :bar_ts, :utc_datetime, null: false
      add :horizon_m, :integer, null: false
      add :confidence, :float, null: false
      # +1 up / -1 down / 0 flat, matching the `side` column of the prediction dumps.
      add :side, :integer, null: false
      add :price, :float
      # Whether M2's own serve-side gate approved this bar. Under §3.1 the policy owns
      # coverage and this is a reported diagnostic, but it is also the signal-only arm's
      # entry condition, so it is recorded rather than discarded.
      add :gated, :boolean, null: false, default: false
      add :regime, :float

      timestamps(updated_at: false)
    end

    create unique_index(:policy_bars, [:pair, :bar_ts, :horizon_m])
    # The coverage threshold is "the k-th largest confidence in the trailing window", which
    # is a range scan on bar_ts ordered by confidence.
    create index(:policy_bars, [:bar_ts])
    create index(:policy_bars, [:bar_ts, :confidence])
  end
end
