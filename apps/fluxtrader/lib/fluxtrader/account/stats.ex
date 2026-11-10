defmodule FluxTrader.Account.Stats do
  @moduledoc """
  The account page's numbers: closed deals per month, bot vs manual, as % of the month's
  notional deposit (`Account.NotionalDeposit`).

  ## Where each side starts (Vadim, 2026-11-10)

    * **bot** — every deal closed from 2026-11-01 (all of November).
    * **manual** — every deal closed from `@manual_since`: the two positions open at the start
      (ADA, SOL — opened before it, counted whole when they close) and everything after.
      Manual deals already closed in November before it are ignored.
  """
  import Ecto.Query

  alias FluxTrader.Account.{Deals, Fill, Income, NotionalDeposit}
  alias FluxTrader.Repo
  alias FluxTrader.Trading.{LivePilot, PaperTrade}

  @bot_since ~U[2026-11-01 00:00:00Z]
  @manual_since ~U[2026-11-10 00:00:00Z]

  def bot_since, do: @bot_since
  def manual_since, do: @manual_since

  @doc "Every order id the `live` arm recorded."
  def bot_order_ids do
    from(t in PaperTrade,
      where: t.arm == ^LivePilot.arm(),
      select: [t.entry_order_id, t.exit_order_id]
    )
    |> Repo.all()
    |> List.flatten()
    |> Enum.reject(&is_nil/1)
    |> MapSet.new()
  end

  @doc "All deals rebuilt from the synced fills, owners set."
  def deals do
    fills = Repo.all(from(f in Fill))
    funding = Repo.all(from(i in Income, where: i.income_type == "FUNDING_FEE"))
    Deals.build(fills, funding, bot_order_ids())
  end

  @doc "Whether a closed deal counts on the page (its side's start date)."
  def counted?(%{closed_at: nil}), do: false
  def counted?(%{owner: :bot, closed_at: t}), do: DateTime.compare(t, @bot_since) != :lt
  def counted?(%{owner: :manual, closed_at: t}), do: DateTime.compare(t, @manual_since) != :lt

  @doc """
  One row per month and owner (bot first), newest month first. The current month always has
  both rows, empty or not. `result_pct = net_usd / deposit_usd × 100`.
  """
  def monthly(deals, now \\ DateTime.utc_now(), hist \\ NotionalDeposit.history()) do
    counted = Enum.filter(deals, &counted?/1)
    current = {now.year, now.month}

    months =
      counted
      |> Enum.map(&{&1.closed_at.year, &1.closed_at.month})
      |> Enum.concat([current])
      |> Enum.uniq()
      |> Enum.sort(:desc)

    for month <- months, owner <- [:bot, :manual] do
      ds = Enum.filter(counted, &({&1.closed_at.year, &1.closed_at.month} == month and &1.owner == owner))
      deposit = NotionalDeposit.for_month(month, hist)
      net = sum(ds, :net)

      %{
        month: NotionalDeposit.month_key(month),
        owner: owner,
        deals: length(ds),
        wins: Enum.count(ds, &(&1.net > 0)),
        pnl_usd: sum(ds, :pnl),
        fees_usd: sum(ds, :fees),
        funding_usd: sum(ds, :funding),
        net_usd: net,
        deposit_usd: deposit,
        result_pct: net / deposit * 100
      }
    end
  end

  @doc "Counted closed deals, newest first."
  def recent(deals, n \\ 50) do
    deals |> Enum.filter(&counted?/1) |> Enum.reverse() |> Enum.take(n)
  end

  @doc "Deals still open (both owners)."
  def open(deals), do: Enum.filter(deals, &is_nil(&1.closed_at))

  defp sum(ds, k), do: ds |> Enum.map(&Map.fetch!(&1, k)) |> Enum.sum() |> Kernel.*(1.0)
end
