defmodule FluxTrader.Account.NotionalDeposit do
  @moduledoc """
  The notional deposit: the USD figure the account page divides results by, and the base the
  live pilot sizes from. Not the account balance (on 2026-11-10 the wallet held ~$557 against
  a $1000 notional deposit).

  Stored in `app_settings` under `notional_deposit` as a history of
  `%{"from" => "YYYY-MM", "usd" => float, "set_at" => iso8601}`. A change takes effect for the
  whole month it is made in and every later month; a month before it keeps the value in force
  then. Two changes in one month: the later wins for that month.

  With no history the deposit is `LivePilot`'s `capital_usd` (`LIVE_PILOT_CAPITAL_USD`) for
  every month — the pilot's sizing then reads exactly as it did before this module existed.
  """
  alias FluxTrader.Settings

  @key "notional_deposit"

  @doc "The history, oldest month first."
  def history do
    case Settings.get(@key) do
      %{"history" => rows} when is_list(rows) -> Enum.sort_by(rows, & &1["from"])
      _ -> []
    end
  end

  @doc "The deposit in force for `month` (`{year, month}` or a Date/DateTime in it)."
  def for_month(month, hist \\ nil) do
    key = month_key(month)

    (hist || history())
    |> Enum.filter(&(&1["from"] <= key))
    |> List.last()
    |> case do
      %{"usd" => usd} when is_number(usd) -> usd * 1.0
      _ -> default()
    end
  end

  @doc "The deposit in force now."
  def current(now \\ DateTime.utc_now()), do: for_month(now)

  @doc "Set the deposit from `now`'s month on. Rejects anything not a positive number."
  def put(usd, now \\ DateTime.utc_now())

  def put(usd, now) when is_number(usd) and usd > 0 do
    key = month_key(now)
    row = %{"from" => key, "usd" => usd * 1.0, "set_at" => DateTime.to_iso8601(now)}
    rows = Enum.reject(history(), &(&1["from"] == key)) ++ [row]

    with {:ok, _} <- Settings.put(@key, %{"history" => Enum.sort_by(rows, & &1["from"])}) do
      {:ok, usd * 1.0}
    end
  end

  def put(_, _), do: {:error, :not_a_positive_number}

  @doc "The fallback: the pilot's configured capital."
  def default, do: FluxTrader.Trading.LivePilot.config()[:capital_usd] * 1.0

  def month_key({y, m}), do: "#{y}-#{String.pad_leading(Integer.to_string(m), 2, "0")}"
  def month_key(%{year: y, month: m}), do: month_key({y, m})
end
