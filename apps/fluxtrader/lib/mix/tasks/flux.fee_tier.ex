defmodule Mix.Tasks.Flux.FeeTier do
  @shortdoc "Check the account's real Binance USDⓈ-M commission rate against what the ledger charges"

  @moduledoc """
  Verify the fee tier every M3 cost number rests on.

      docker compose exec app mix flux.fee_tier
      docker compose exec app mix flux.fee_tier --symbol ETHUSDT

  ## Why this exists

  M3-4 decomposed its measured crossing cost into **4.0 bps taker / 2.0 bps maker per
  side** — what it took to be the published VIP-0 rate — and every number in
  `docs/M3_4_RESULTS.md` was built on that. **On 2026-09-10 this task read the account and
  found taker 5.0 / maker 2.0**: 4.0 is the BNB-discounted rate, which nobody had enabled.
  `Trading.ExecCost` now carries the verified fee and adds the 2.0 bps round-trip
  correction to every measured cost; this task compares the account against the *verified*
  constant, so a MATCH means the correction still holds and a MISMATCH means the tier has
  moved again and `ExecCost` needs a new constant.

  ## What it needs, and what it does when it cannot get it

  `GET /fapi/v1/commissionRate` is a signed USER_DATA endpoint: it needs `BINANCE_API_KEY`
  and `BINANCE_API_SECRET` (a READ-ONLY key is enough and is what should be used). Without
  them the task reports the constant and exits non-zero rather than printing a reassuring
  number it did not verify. It goes wherever `Binance.Client.trade_url/0` points, and says
  so — the testnet's fee schedule is not the account's.
  """
  use Mix.Task

  alias FluxTrader.Binance.{Client, Trade}
  alias FluxTrader.Trading.ExecCost

  @impl Mix.Task
  def run(argv) do
    {opts, _, _} = OptionParser.parse(argv, strict: [symbol: :string])
    symbol = Keyword.get(opts, :symbol, "BTCUSDT")

    Mix.Task.run("app.config")
    Application.ensure_all_started(:finch)
    {:ok, _} = Finch.start_link(name: FluxTrader.Finch)

    charged_taker = ExecCost.taker_fee_bps_per_side()
    charged_maker = ExecCost.maker_fee_bps_per_side()

    IO.puts("""
    M3-4 measured its crossing costs at taker #{fmt(ExecCost.measured_fee_bps_per_side())} bps/side.
    The ledger charges taker #{fmt(charged_taker)} / maker #{fmt(charged_maker)} bps/side
    (verified #{ExecCost.fee_verified_on()}; correction +#{fmt(ExecCost.fee_correction_bps())} bps per round trip).
    Host: #{Client.trade_url()}#{if Client.testnet?(), do: "  ⚠️ TESTNET — not the account's schedule", else: ""}
    """)

    unless Client.credentials?() do
      Mix.shell().error("""
      BINANCE_API_KEY / BINANCE_API_SECRET are not set in this container, so the account's
      real tier CANNOT be read. The constant above stays UNVERIFIED for today.

      Set them (a read-only key) and re-run:
        BINANCE_API_KEY=... BINANCE_API_SECRET=... docker compose exec app mix flux.fee_tier
      """)

      exit({:shutdown, 1})
    end

    case Trade.impl().commission_rate(symbol) do
      {:ok, %{"makerCommissionRate" => maker, "takerCommissionRate" => taker}} ->
        report(symbol, to_bps(taker), to_bps(maker), charged_taker)

      {:ok, body} ->
        Mix.shell().error("unexpected response: #{inspect(body)}")
        exit({:shutdown, 1})

      {:error, reason} ->
        Mix.shell().error("commissionRate request failed: #{inspect(reason)}")
        exit({:shutdown, 1})
    end
  end

  defp report(symbol, taker_bps, maker_bps, charged_taker) do
    IO.puts("""
    Account rate for #{symbol}:
      taker #{fmt(taker_bps)} bps/side   maker #{fmt(maker_bps)} bps/side
    """)

    delta = taker_bps - charged_taker

    if abs(delta) < 0.01 do
      IO.puts("MATCH — the account pays what the ledger charges; ExecCost's correction stands.")
    else
      IO.puts("""
      MISMATCH — the account's taker fee is #{fmt(delta)} bps/side away from what the ledger
      charges, i.e. #{fmt(delta * 2)} bps per round trip on every forward number, in the
      #{if delta > 0, do: "ledger-is-too-optimistic", else: "ledger-is-too-pessimistic"} direction.

      Update `@verified_taker_fee_bps_per_side` in Trading.ExecCost (and the date), re-run the
      exec_cost tests, and record the change in docs/M3_4_RESULTS.md §2 before anything else.
      """)

      exit({:shutdown, 2})
    end
  end

  # Binance reports a rate, e.g. "0.000500" = 5 bps.
  defp to_bps(rate) when is_binary(rate), do: String.to_float(rate) * 1.0e4
  defp to_bps(rate) when is_number(rate), do: rate * 1.0e4

  defp fmt(x), do: :erlang.float_to_binary(x * 1.0, decimals: 3)
end
