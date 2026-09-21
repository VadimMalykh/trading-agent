defmodule FluxTrader.Trading.LivePilot do
  @moduledoc """
  The real-money micro-pilot (2026-09-21): arm `live`.

  ## What it is

  Every time the paper `policy` arm opens a row, this arm places the same side on the
  exchange at a small **flat** notional, holds it for the same four hours behind the same
  2% / 4% brake, and books the exchange's fills under arm `live`. The executor's mode stays
  `simulation`: the `policy` and `flat_size` rows stay paper, so the registered forward A/B
  is untouched — which is the objection REAL_MONEY_TRACK §4 raised against switching the VM
  to `auto`.

  ## What it is for

  Operations, not evidence: real fills against the paper price, the brake on a real book,
  the user-data stream, the account plumbing. At ~$100 a trade the expected P&L is cents.
  Nothing here may be quoted for or against the policy; R0–R5 do not read this arm.

  ## Its own limits, none shared with `RiskManager`

  `RiskManager` holds the paper policy arm's slots and daily loss in memory. The pilot's
  limits are derived from its own ledger rows on every check, so a restart cannot reset them:

    * `max_positions` open `live` rows,
    * `daily_loss_usd` realised since 00:00 UTC,
    * `max_total_loss_usd` realised since the first `live` row — the kill level. Once hit
      the pilot stays refused until an operator raises it.

  ## Enabling it

  `LIVE_PILOT=true` **and** a key with futures-trading rights **and** the executor not in
  `auto` (there the policy arm already trades, and two arms would double the position).
  Runbook: `docs/REAL_MONEY_TRACK.md` §7.
  """
  alias FluxTrader.Binance.Client
  alias FluxTrader.Trading.Ledger

  @arm "live"

  @defaults [
    enabled: false,
    capital_usd: 500.0,
    notional_usd: 100.0,
    leverage: 1,
    max_positions: 4,
    daily_loss_usd: 10.0,
    max_total_loss_usd: 100.0
  ]

  def arm, do: @arm

  def config do
    Keyword.merge(@defaults, Application.get_env(:fluxtrader, :live_pilot, []))
  end

  @doc "Requested, credentialed, and not doubling an `auto` executor."
  def enabled?, do: refusal() == nil

  @doc "Why the pilot is off, or nil when it is on."
  def refusal do
    cond do
      config()[:enabled] != true -> :not_requested
      not Client.credentials?() -> :missing_credentials
      trading_mode() == "auto" -> :executor_is_auto
      true -> nil
    end
  end

  @doc """
  Approve or refuse mirroring one opened policy decision. Returns `{:ok, order}` shaped like
  `RiskManager.check/1`'s (quantity, notional, leverage, stop, target) or `{:reject, reason}`.
  """
  def check(decision, now \\ DateTime.utc_now()) do
    cfg = config()

    cond do
      refusal() != nil ->
        {:reject, refusal()}

      Ledger.realised_usd(@arm) <= -cfg[:max_total_loss_usd] ->
        {:reject, :total_loss_limit}

      Ledger.realised_usd(@arm, start_of_day(now)) <= -cfg[:daily_loss_usd] ->
        {:reject, :daily_loss_limit}

      MapSet.size(Ledger.open_pairs(@arm)) >= cfg[:max_positions] ->
        {:reject, :max_positions}

      true ->
        {:ok,
         %{
           quantity: cfg[:notional_usd] / decision.entry_price,
           notional: cfg[:notional_usd] * 1.0,
           leverage: cfg[:leverage],
           stop_loss: brake(decision, -1.0),
           take_profit: brake(decision, take_profit_ratio())
         }}
    end
  end

  @doc "Everything `/api/health` reports about the pilot."
  def status(now \\ DateTime.utc_now()) do
    cfg = config()

    %{
      arm: @arm,
      enabled: enabled?(),
      refusal: refusal(),
      capital_usd: cfg[:capital_usd],
      notional_usd: cfg[:notional_usd],
      leverage: cfg[:leverage],
      max_positions: cfg[:max_positions],
      daily_loss_usd: cfg[:daily_loss_usd],
      max_total_loss_usd: cfg[:max_total_loss_usd],
      open: MapSet.size(Ledger.open_pairs(@arm)),
      realised_usd_today: Ledger.realised_usd(@arm, start_of_day(now)),
      realised_usd_total: Ledger.realised_usd(@arm)
    }
  end

  # The same 2% stop and 2:1 target `RiskManager` attaches, read from the same config so the
  # pilot's brake is the one REAL_MONEY_TRACK Q2 decided and X6 priced.
  defp brake(%{side: side, entry_price: p}, multiple) do
    p * (1 + side * multiple * stop_loss_pct())
  end

  defp stop_loss_pct, do: Keyword.get(trading(), :stop_loss_pct, 0.02)
  defp take_profit_ratio, do: Keyword.get(trading(), :take_profit_ratio, 2.0)
  defp trading_mode, do: Keyword.get(trading(), :mode, "simulation")
  defp trading, do: Application.get_env(:fluxtrader, :trading, [])

  defp start_of_day(now), do: DateTime.new!(DateTime.to_date(now), ~T[00:00:00], "Etc/UTC")
end
