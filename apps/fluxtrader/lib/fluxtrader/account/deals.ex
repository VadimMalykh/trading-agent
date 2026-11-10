defmodule FluxTrader.Account.Deals do
  @moduledoc """
  Rebuild flat-to-flat deals from the account's fills, and split them bot / manual.

  Pure: no Repo, no HTTP. `FluxTrader.Account.Stats` feeds it from the tables.

  ## A deal

  Per symbol, fills in time order move one net position (the account is one-way: Binance's
  `dualSidePosition` is false, every position is `BOTH`). A deal opens when the position leaves
  zero and closes when it returns to zero. A fill that crosses zero closes the deal and opens
  the next one with the remainder; its commission is split by quantity.

  `net = pnl − fees + funding`, all USDT:
    * `pnl` — Binance's `realizedPnl` of every fill in the deal,
    * `fees` — commission of every fill, opening fills included (USDT only; a fee in another
      asset is counted in `fees_other` and left out of `net`),
    * `funding` — every `FUNDING_FEE` row on the symbol while the deal was open.

  A deal is booked whole in the month it closes — a partial close does not book early.

  ## Owner

  A deal is the bot's when any of its fills carries an order id the `live` arm recorded
  (`entry_order_id` / `exit_order_id`, both verified equal to the exchange's `orderId`). The
  pilot only opens on a flat symbol (`Executor.foreign_position?/2`), so a bot deal starts with
  the bot's own order. Everything else is manual.
  """

  @type deal :: %{
          symbol: String.t(),
          side: 1 | -1,
          opened_at: DateTime.t(),
          closed_at: DateTime.t() | nil,
          qty: float(),
          max_qty: float(),
          pnl: float(),
          fees: float(),
          fees_other: float(),
          funding: float(),
          net: float(),
          fills: non_neg_integer(),
          order_ids: MapSet.t(),
          owner: :bot | :manual | nil
        }

  @doc """
  Every deal in `fills` (maps with `symbol, order_id, side, qty, realized_pnl, commission,
  commission_asset, time` and optionally `trade_id`), with `funding` (maps with `symbol,
  income, time`) attached and the owner set from `bot_order_ids`. Closed and open deals both;
  `closed_at` nil means still open.
  """
  def build(fills, funding \\ [], bot_order_ids \\ MapSet.new()) do
    fills
    |> Enum.group_by(& &1.symbol)
    |> Enum.flat_map(fn {_symbol, fs} -> symbol_deals(fs) end)
    |> attach_funding(funding)
    |> Enum.map(&finish(&1, bot_order_ids))
    |> Enum.sort_by(&{usec(&1.closed_at), usec(&1.opened_at)})
  end

  # Open deals (nil) sort last.
  defp usec(nil), do: :infinity
  defp usec(%DateTime{} = t), do: DateTime.to_unix(t, :microsecond)

  defp symbol_deals(fills) do
    fills
    |> Enum.sort_by(&{DateTime.to_unix(&1.time, :microsecond), Map.get(&1, :trade_id, 0)})
    |> Enum.reduce({nil, []}, &step/2)
    |> then(fn
      {nil, done} -> Enum.reverse(done)
      {open, done} -> Enum.reverse([open | done])
    end)
  end

  defp step(f, {nil, done}), do: {open_deal(f, signed(f), 1.0), done}

  defp step(f, {deal, done}) do
    s = signed(f)
    new = deal.qty + s

    cond do
      flat?(new, deal.qty, s) ->
        closed = deal |> add_fill(f, 1.0, f.realized_pnl) |> Map.merge(%{qty: 0.0, closed_at: f.time})
        {nil, [closed | done]}

      sign(new) == sign(deal.qty) ->
        deal = deal |> add_fill(f, 1.0, f.realized_pnl) |> Map.put(:qty, new)
        {%{deal | max_qty: max(deal.max_qty, abs(new))}, done}

      true ->
        # Crosses zero: the closing part ends this deal, the rest opens the next.
        frac = abs(deal.qty) / abs(s)
        closed = deal |> add_fill(f, frac, f.realized_pnl) |> Map.merge(%{qty: 0.0, closed_at: f.time})
        {open_deal(f, new, 1.0 - frac), [closed | done]}
    end
  end

  defp open_deal(f, qty, frac) do
    base = %{
      symbol: f.symbol,
      side: sign(qty),
      opened_at: f.time,
      closed_at: nil,
      qty: qty,
      max_qty: abs(qty),
      pnl: 0.0,
      fees: 0.0,
      fees_other: 0.0,
      funding: 0.0,
      net: 0.0,
      fills: 0,
      order_ids: MapSet.new(),
      owner: nil
    }

    add_fill(base, f, frac, 0.0)
  end

  defp add_fill(deal, f, frac, pnl) do
    {fees, other} =
      if f.commission_asset in ["USDT", nil],
        do: {deal.fees + f.commission * frac, deal.fees_other},
        else: {deal.fees, deal.fees_other + f.commission * frac}

    %{
      deal
      | pnl: deal.pnl + pnl,
        fees: fees,
        fees_other: other,
        fills: deal.fills + 1,
        order_ids: MapSet.put(deal.order_ids, f.order_id)
    }
  end

  defp attach_funding(deals, funding) do
    Enum.reduce(funding, deals, fn row, deals ->
      case Enum.find_index(deals, &holds?(&1, row)) do
        nil -> deals
        i -> List.update_at(deals, i, &%{&1 | funding: &1.funding + row.income})
      end
    end)
  end

  defp holds?(deal, %{symbol: sym, time: t}) do
    deal.symbol == sym and DateTime.compare(deal.opened_at, t) != :gt and
      (deal.closed_at == nil or DateTime.compare(t, deal.closed_at) != :gt)
  end

  defp finish(deal, bot_ids) do
    owner = if MapSet.disjoint?(deal.order_ids, bot_ids), do: :manual, else: :bot
    %{deal | net: deal.pnl - deal.fees + deal.funding, owner: owner}
  end

  defp signed(%{side: "BUY", qty: q}), do: q * 1.0
  defp signed(%{side: "SELL", qty: q}), do: -q * 1.0

  defp flat?(new, before, s), do: abs(new) <= 1.0e-9 * max(abs(before), abs(s))

  defp sign(x) when x > 0, do: 1
  defp sign(_), do: -1
end
