defmodule Mix.Tasks.Flux.FeeTier do
  @shortdoc "Check the account's real Binance USDⓈ-M commission rate against what M3-4 assumed"

  @moduledoc """
  Verify the fee tier every M3 cost number rests on.

      docker compose exec app mix flux.fee_tier
      docker compose exec app mix flux.fee_tier --symbol ETHUSDT

  ## Why this exists

  `ml/train/m3/metrics.py` charges 14 bps taker and 5 bps maker round trip, which decompose
  to **4.0 bps taker and 2.0 bps maker per side** — the published Binance USDⓈ-M VIP-0
  rates. M3-4's whole cost study is built on that decomposition and **it has never been
  checked against the account.** A different tier shifts every number in
  `docs/M3_4_RESULTS.md` and `docs/M3_2_RESULTS.md` by a constant.
  M3_4_PROTOCOL §2.5 makes this a precondition of M3-5, which is why it is a task and not a
  note.

  ## What it needs, and what it does when it cannot get it

  `GET /fapi/v1/commissionRate` is a signed USER_DATA endpoint: it needs `BINANCE_API_KEY`
  and `BINANCE_API_SECRET` in the app's environment. Without them the task reports the
  assumption and exits non-zero rather than printing a reassuring number it did not verify —
  an unverified constant that looks verified is worse than a missing one.
  """
  use Mix.Task

  @assumed_taker_bps 4.0
  @assumed_maker_bps 2.0
  @base_url "https://fapi.binance.com"

  @impl Mix.Task
  def run(argv) do
    {opts, _, _} = OptionParser.parse(argv, strict: [symbol: :string])
    symbol = Keyword.get(opts, :symbol, "BTCUSDT")

    Application.ensure_all_started(:finch)
    {:ok, _} = Finch.start_link(name: __MODULE__.Finch)

    key = System.get_env("BINANCE_API_KEY")
    secret = System.get_env("BINANCE_API_SECRET")

    IO.puts("""
    Assumed by every M3 cost number (metrics.py, M3_4_RESULTS.md):
      taker #{@assumed_taker_bps} bps/side   maker #{@assumed_maker_bps} bps/side
      -> #{@assumed_taker_bps * 2} bps taker round trip in fees alone
    """)

    if blank?(key) or blank?(secret) do
      Mix.shell().error("""
      BINANCE_API_KEY / BINANCE_API_SECRET are not set in this container, so the account's
      real tier CANNOT be read. The assumption above stays UNVERIFIED.

      Set them and re-run:
        BINANCE_API_KEY=... BINANCE_API_SECRET=... docker compose exec app mix flux.fee_tier
      """)

      exit({:shutdown, 1})
    end

    case fetch(symbol, key, secret) do
      {:ok, %{"makerCommissionRate" => maker, "takerCommissionRate" => taker}} ->
        report(symbol, to_bps(taker), to_bps(maker))

      {:ok, body} ->
        Mix.shell().error("unexpected response: #{inspect(body)}")
        exit({:shutdown, 1})

      {:error, reason} ->
        Mix.shell().error("commissionRate request failed: #{inspect(reason)}")
        exit({:shutdown, 1})
    end
  end

  defp report(symbol, taker_bps, maker_bps) do
    IO.puts("""
    Account rate for #{symbol}:
      taker #{fmt(taker_bps)} bps/side   maker #{fmt(maker_bps)} bps/side
    """)

    delta = taker_bps - @assumed_taker_bps

    if abs(delta) < 0.01 do
      IO.puts("MATCH — the taker assumption is correct; M3-4's numbers stand as published.")
    else
      IO.puts("""
      MISMATCH — the taker fee is #{fmt(delta)} bps/side away from the assumption, i.e.
      #{fmt(delta * 2)} bps per round trip on EVERY published M3 number, in the
      #{if delta > 0, do: "pessimistic-was-too-optimistic", else: "too-pessimistic"} direction.

      This does not require a re-run of M3-4: the study reports gross components, so the
      correction is a constant. It DOES require correcting docs/M3_4_RESULTS.md §2 and the
      economics quoted in docs/M3_PLAN.md §0.8 before anything is promoted.
      """)
    end
  end

  defp fetch(symbol, key, secret) do
    ts = System.system_time(:millisecond)
    query = URI.encode_query(symbol: symbol, timestamp: ts, recvWindow: 5000)
    sig = :crypto.mac(:hmac, :sha256, secret, query) |> Base.encode16(case: :lower)
    url = "#{@base_url}/fapi/v1/commissionRate?#{query}&signature=#{sig}"

    case Finch.build(:get, url, [{"X-MBX-APIKEY", key}])
         |> Finch.request(__MODULE__.Finch, receive_timeout: 15_000) do
      {:ok, %{status: 200, body: body}} -> Jason.decode(body)
      {:ok, %{status: s, body: body}} -> {:error, {s, body}}
      {:error, reason} -> {:error, reason}
    end
  end

  # Binance reports a rate, e.g. "0.000400" = 4 bps.
  defp to_bps(rate) when is_binary(rate), do: String.to_float(rate) * 1.0e4
  defp to_bps(rate) when is_number(rate), do: rate * 1.0e4

  defp fmt(x), do: :erlang.float_to_binary(x * 1.0, decimals: 3)

  defp blank?(nil), do: true
  defp blank?(""), do: true
  defp blank?(_), do: false
end
