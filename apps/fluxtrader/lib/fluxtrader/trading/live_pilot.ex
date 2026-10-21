defmodule FluxTrader.Trading.LivePilot do
  @moduledoc """
  The real-money micro-pilot (2026-09-21): arm `live`.

  ## What it is

  Every time the paper `policy` arm opens a row, this arm places the same side on the
  exchange at a small **flat** notional, holds it for the same four hours behind a stop and a
  target, and books the exchange's fills under arm `live`. The stop is `LIVE_PILOT_STOP_PCT`
  (the target `TAKE_PROFIT_RATIO` times it); without that variable it is `RiskManager`'s 2 %.
  🔴 2026-10-19 (REAL_MONEY_TRACK §7): the 2 % stop fired on 13 of the pilot's first 38 trades
  and was ~80 % of its gap to the paper arm — a 2 % brake on a rule scored with a four-hour
  timer is a different rule. The VM runs 10 %: no paper trade of the fifth start (209, worst
  −7.9 %) reached it, so the pilot mirrors the scored exit and the stop is a catastrophe cover. The executor's mode stays
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
    max_total_loss_usd: 100.0,
    # nil → RiskManager's STOP_LOSS_PCT (2 %); the VM sets LIVE_PILOT_STOP_PCT=0.10.
    stop_pct: nil,
    # M2 (BOOK_WAVE2_PLAN §M2): rest at the touch for `maker_wait_s`, then cross. The
    # pilot's arm only; the paper arms never see it. W is registered at 60 s and has no
    # environment knob — only a test may set it.
    maker_path: false,
    maker_wait_s: 60
  ]

  def arm, do: @arm

  def config do
    Keyword.merge(@defaults, Application.get_env(:fluxtrader, :live_pilot, []))
  end

  @doc "Requested, credentialed, and not doubling an `auto` executor."
  def enabled?, do: refusal() == nil

  @doc "Whether the pilot's orders take the maker path (M2). Off by default."
  def maker_path?, do: config()[:maker_path] == true

  @doc "The maker path's W, seconds a leg rests before the remainder is crossed."
  def maker_wait_s, do: config()[:maker_wait_s] * 1.0

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
      stop_pct: stop_loss_pct(),
      take_profit_pct: stop_loss_pct() * take_profit_ratio(),
      daily_loss_usd: cfg[:daily_loss_usd],
      max_total_loss_usd: cfg[:max_total_loss_usd],
      maker_path: maker_path?(),
      maker_wait_s: maker_wait_s(),
      open: MapSet.size(Ledger.open_pairs(@arm)),
      realised_usd_today: Ledger.realised_usd(@arm, start_of_day(now)),
      realised_usd_total: Ledger.realised_usd(@arm)
    }
  end

  # The stop is the pilot's own `stop_pct` when set (LIVE_PILOT_STOP_PCT), else the 2 % stop
  # `RiskManager` attaches on the auto path; the target is TAKE_PROFIT_RATIO times the stop
  # either way (at 10 % that is 20 % — effectively never, as the timer-only rule intends).
  defp brake(%{side: side, entry_price: p}, multiple) do
    p * (1 + side * multiple * stop_loss_pct())
  end

  defp stop_loss_pct do
    case config()[:stop_pct] do
      pct when is_number(pct) and pct > 0 -> pct * 1.0
      _ -> Keyword.get(trading(), :stop_loss_pct, 0.02)
    end
  end

  defp take_profit_ratio, do: Keyword.get(trading(), :take_profit_ratio, 2.0)
  defp trading_mode, do: Keyword.get(trading(), :mode, "simulation")
  defp trading, do: Application.get_env(:fluxtrader, :trading, [])

  defp start_of_day(now), do: DateTime.new!(DateTime.to_date(now), ~T[00:00:00], "Etc/UTC")
end
