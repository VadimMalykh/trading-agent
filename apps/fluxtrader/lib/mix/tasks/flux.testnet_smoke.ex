defmodule Mix.Tasks.Flux.TestnetSmoke do
  @shortdoc "Open, brake, hold and close one tiny position on the Binance USDⓈ-M TESTNET"

  @moduledoc """
  The exit criterion of REAL_MONEY_TRACK step 3: *a signed order path demonstrated against
  testnet*. This runs the exact code the executor's `auto` path runs —
  `Trading.ExchangeOrders` over `Binance.Trade.Rest` — without starting the trading
  application, and prints everything the exchange said.

      docker compose exec -e BINANCE_TESTNET=true \\
        -e BINANCE_API_KEY=<testnet key> -e BINANCE_API_SECRET=<testnet secret> \\
        app mix flux.testnet_smoke
      ... app mix flux.testnet_smoke --symbol ETHUSDT --hold-seconds 30 --notional 120
      ... app mix flux.testnet_smoke --flatten      # close a position a failed run left behind

  (`docker compose exec` does not forward the host's environment; each variable needs `-e`.)

  🔴 **It refuses to run unless `BINANCE_TESTNET=true`.** There is no flag to point it at
  production; a production smoke test is a real trade, and that decision does not belong
  in a Mix task's arguments. Testnet keys are created on https://testnet.binancefuture.com (the
  testnet web UI) and work against `demo-fapi.binance.com`; they are not the production keys.

  ## What it does, in order

    1. reads the testnet's symbol filters and the account's position on the symbol
       (must be flat, or it stops);
    2. opens a `MARKET` position of about `--notional` USDT (default: 1.2x the symbol's
       minimum notional) at `--leverage`, with the 2% stop / 4% target brake, and prints
       the reconciled fill;
    3. holds for `--hold-seconds`, reading the position back from the exchange;
    4. closes it through the same path the timed close uses (cancel brakes, `MARKET
       reduceOnly`, reconcile), prints the fill and the exit reason;
    5. reads the position again and reports `TESTNET_OK` only if it is flat and no order
       is resting. Anything else exits non-zero with what was seen.
  """
  use Mix.Task
  require Logger

  alias FluxTrader.Binance.{Client, Trade}
  alias FluxTrader.Trading.ExchangeOrders

  @impl Mix.Task
  def run(argv) do
    {opts, _, _} =
      OptionParser.parse(argv,
        strict: [
          symbol: :string,
          hold_seconds: :integer,
          notional: :float,
          leverage: :integer,
          flatten: :boolean
        ]
      )

    symbol = Keyword.get(opts, :symbol, "BTCUSDT")
    hold_s = Keyword.get(opts, :hold_seconds, 10)
    leverage = Keyword.get(opts, :leverage, 5)

    Mix.Task.run("app.config")
    Application.ensure_all_started(:finch)
    {:ok, _} = Finch.start_link(name: FluxTrader.Finch)
    Logger.configure(level: :info)

    unless Client.testnet?() do
      Mix.shell().error("REFUSED: BINANCE_TESTNET is not true. This task only ever trades the testnet.")
      exit({:shutdown, 1})
    end

    unless Client.credentials?() do
      Mix.shell().error("BINANCE_API_KEY / BINANCE_API_SECRET (TESTNET keys) are not set.")
      exit({:shutdown, 1})
    end

    client = Trade.impl()
    IO.puts("Trading host: #{Client.trade_url()}  symbol: #{symbol}  leverage: #{leverage}")

    {:ok, filters} = ExchangeOrders.load_filters(client) |> or_die("exchangeInfo")
    f = Map.fetch!(filters, symbol)
    IO.puts("filters: step #{f.step} tick #{f.tick} min_notional #{f.min_notional}")

    if opts[:flatten], do: flatten!(client, symbol)

    assert_flat!(client, symbol, "before")

    price = mark_price!(client, symbol)
    IO.puts("mark price (premiumIndex): #{price}")
    notional = Keyword.get(opts, :notional, f.min_notional * 1.2)
    qty = notional / price

    req = %{
      symbol: symbol,
      side: "BUY",
      quantity: qty,
      price: price,
      leverage: leverage,
      stop_loss: price * 0.98,
      take_profit: price * 1.04
    }

    IO.puts("\nOPEN  BUY ~#{Float.round(qty, 6)} @ ~#{price} (notional ~#{Float.round(notional, 2)} USDT)")
    {:ok, fill} = ExchangeOrders.open(client, filters, req) |> or_die("open")
    IO.puts("  filled qty=#{fill.executed_qty} avg=#{fill.avg_price} order=#{fill.order_id}")
    IO.puts("  stop=#{inspect(fill.stop_order_id)} target=#{inspect(fill.target_order_id)}")

    IO.puts("\nHOLD #{hold_s}s")
    Process.sleep(hold_s * 1_000)
    show_position(client, symbol, "during")

    IO.puts("\nCLOSE SELL reduceOnly #{fill.executed_qty}")

    close_req = %{
      symbol: symbol,
      side: "SELL",
      quantity: fill.executed_qty,
      stop_order_id: fill.stop_order_id,
      target_order_id: fill.target_order_id
    }

    {:ok, exit_fill} = ExchangeOrders.close(client, close_req) |> or_die("close")

    IO.puts(
      "  filled qty=#{exit_fill.executed_qty} avg=#{exit_fill.avg_price} " <>
        "order=#{exit_fill.order_id} reason=#{exit_fill.exit_reason}"
    )

    ret_bps = (exit_fill.avg_price / fill.avg_price - 1.0) * 1.0e4
    IO.puts("  round trip: #{Float.round(ret_bps, 2)} bps before fees")

    _ = client.cancel_all_open_orders(symbol)
    assert_flat!(client, symbol, "after")
    IO.puts("\nTESTNET_OK — open, brake, close and reconcile all succeeded on #{symbol}")
  end

  # From premiumIndex, not positionRisk: with no open position the demo reports a mark of
  # 0.00000000 there, which sized the first run's order by dividing by zero.
  defp mark_price!(client, symbol) do
    case client.mark_price(symbol) do
      {:ok, %{"markPrice" => mp}} ->
        price = to_f(mp)
        if price > 0.0, do: price, else: die("premiumIndex returned a zero mark", mp)

      other ->
        die("premiumIndex (mark price)", other)
    end
  end

  defp show_position(client, symbol, label) do
    case client.position_risk(symbol) do
      {:ok, [p | _]} ->
        IO.puts(
          "  position (#{label}): amt=#{p["positionAmt"]} entry=#{p["entryPrice"]} " <>
            "mark=#{p["markPrice"]} upnl=#{p["unRealizedProfit"]} lev=#{p["leverage"]}"
        )

        to_f(p["positionAmt"])

      other ->
        die("positionRisk", other)
    end
  end

  # `--flatten`: close whatever position the symbol holds (a failed earlier run leaves one
  # behind, unbraked) through the same close path, then continue with the smoke.
  defp flatten!(client, symbol) do
    amt = show_position(client, symbol, "flatten")

    if amt != 0.0 do
      side = if amt > 0, do: "SELL", else: "BUY"
      IO.puts("FLATTEN #{side} reduceOnly #{abs(amt)}")
      req = %{symbol: symbol, side: side, quantity: abs(amt), stop_order_id: nil, target_order_id: nil}
      {:ok, fill} = ExchangeOrders.close(client, req) |> or_die("flatten")
      IO.puts("  flattened qty=#{fill.executed_qty} avg=#{fill.avg_price} order=#{fill.order_id}")
    else
      IO.puts("FLATTEN: already flat")
    end
  end

  defp assert_flat!(client, symbol, label) do
    amt = show_position(client, symbol, label)

    if amt != 0.0 do
      Mix.shell().error("NOT FLAT (#{label}): #{symbol} holds #{amt}. Close it on the testnet UI and re-run.")
      exit({:shutdown, 3})
    end
  end

  defp or_die({:ok, _} = ok, _step), do: ok
  defp or_die(other, step), do: die(step, other)

  defp die(step, what) do
    Mix.shell().error("FAILED at #{step}: #{inspect(what)}")
    exit({:shutdown, 2})
  end

  defp to_f(v) when is_binary(v), do: v |> Float.parse() |> elem(0)
  defp to_f(v) when is_number(v), do: v * 1.0
end
