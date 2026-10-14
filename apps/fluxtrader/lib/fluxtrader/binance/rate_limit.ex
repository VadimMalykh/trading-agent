defmodule FluxTrader.Binance.RateLimit do
  @moduledoc """
  The one place that knows how much of Binance's per-IP request budget this node has spent.

  Binance USDⓈ-M allows 2,400 request weight per UTC calendar minute per IP (`REQUEST_WEIGHT`;
  the counter resets at :00, as the `x-mbx-used-weight-1m` header shows). Over it the API
  answers 429; keep calling while over it and the IP is banned (418, "banned until <ms>"),
  and every call made during a ban EXTENDS it — the escalation Binance documents, from two
  minutes up to three days.

  That is what happened on 2026-10-13 (docs/BACKLOG.md, "collector / data quality"): the
  book poll at 500 levels (weight 10 a call, from 2026-10-12 02:17 UTC) plus the trade sweep
  (weight 20 a call, 30–72 calls a minute depending on the hour) crossed 2,400 in the busy
  hours; the client had no guard, so the failed calls kept coming, the 429s turned into bans
  and the bans were extended for 2–4 hours twice (07:26–09:40 and 14:00–18:00 UTC), with
  nothing collected meanwhile.

  Two mechanisms, both fed by `observe/4`, which `Binance.Client` calls after every response
  from the production host:

    * **The hard block.** A 429 or 418 sets `blocked_until`: the `retry-after` header when
      present, else the "banned until" epoch in the body, else the next minute boundary.
      While it stands, `Binance.Client` answers `{:error, :rate_limited}` WITHOUT a network
      request, so a ban is never extended by this node.
    * **The soft caps.** `reserve/3` compares the exchange's own `x-mbx-used-weight-1m` for
      the CURRENT minute (a header from an earlier minute counts as zero — the counter has
      reset) against a cap the caller names and answers `{:wait, ms}` until the minute rolls
      over when the call would cross it. The collector gives the trade sweep the lowest cap
      and the book poll a higher one, so when the budget is short the tape thins first, the
      book second and the weight-1 polls (candles, funding, OI, the policy's own reads) not
      at all. The caps are `config :fluxtrader, :weight_caps` (`trades`, `book`).

  The used weight is the server's number, not a local estimate: it is exact to the
  responses still in flight (at most a handful of calls, ≤ ~80 weight), which the 200+ of
  headroom under 2,400 absorbs. State lives in a public ETS table owned by this process so
  the collector's off-process sweep and the inline polls read it without a call.
  """

  use GenServer
  require Logger

  @table __MODULE__
  @minute_ms 60_000

  @doc "Binance's per-IP REQUEST_WEIGHT limit per UTC minute on USDⓈ-M futures."
  def hard_limit, do: 2_400

  @default_caps [trades: 2_000, book: 2_200]

  def start_link(_opts \\ []), do: GenServer.start_link(__MODULE__, [], name: __MODULE__)

  @impl true
  def init(_) do
    :ets.new(@table, [:named_table, :public, :set, read_concurrency: true])
    {:ok, %{}}
  end

  @doc "The cap configured for `kind` (`:trades` or `:book`)."
  def cap(kind) do
    Application.get_env(:fluxtrader, :weight_caps, [])
    |> Keyword.get(kind, Keyword.fetch!(@default_caps, kind))
  end

  @doc """
  Record what a response from the production host said about the budget.

  `headers` are Finch's (lowercase names); `body` is the decoded JSON (a map) or the raw
  string. Returns `:ok`. Safe to call before `start_link/1` (it is a no-op then).
  """
  def observe(status, headers, body, now_ms \\ now_ms()) do
    if table?() do
      case header(headers, "x-mbx-used-weight-1m") do
        nil -> :ok
        v -> :ets.insert(@table, {:used, parse_int(v), now_ms})
      end

      if status in [418, 429], do: block(status, headers, body, now_ms)
    end

    :ok
  end

  @doc "The ms epoch until which every call is refused, or nil."
  def blocked_until(now_ms \\ now_ms()) do
    case lookup(:blocked_until) do
      until when is_integer(until) and until > now_ms -> until
      _ -> nil
    end
  end

  def blocked?(now_ms \\ now_ms()), do: blocked_until(now_ms) != nil

  @doc """
  The exchange's used weight for the minute `now_ms` falls in. A header seen in an earlier
  minute counts as 0: the counter has reset and the first response of the new minute will
  refresh it. Nothing seen yet is 0.
  """
  def used_weight(now_ms \\ now_ms()) do
    case lookup(:used) do
      {used, at} when div(at, @minute_ms) == div(now_ms, @minute_ms) -> used
      _ -> 0
    end
  end

  @doc """
  `:ok` when a call of `weight` fits under `cap` this minute (or under the hard block's
  absence), else `{:wait, ms}` — the time to the next minute boundary, or to the end of a
  hard block when one stands.
  """
  def reserve(weight, cap, now_ms \\ now_ms()) do
    cond do
      (until = blocked_until(now_ms)) != nil -> {:wait, until - now_ms}
      used_weight(now_ms) + weight > cap -> {:wait, ms_to_next_minute(now_ms)}
      true -> :ok
    end
  end

  @doc "Block on `reserve/3`'s answer, then return `:ok`. For callers running off the collector."
  def wait(weight, cap, now_ms \\ now_ms()) do
    case reserve(weight, cap, now_ms) do
      :ok -> :ok
      {:wait, ms} -> Process.sleep(max(ms, 0))
    end

    :ok
  end

  @doc "Forget everything (tests)."
  def reset, do: if(table?(), do: :ets.delete_all_objects(@table))

  # -- internals ------------------------------------------------------------------------

  defp block(status, headers, body, now_ms) do
    until =
      retry_after_ms(headers, now_ms) || banned_until_ms(body) || next_minute_ms(now_ms)

    previous = lookup(:blocked_until)

    if previous == nil or until > previous do
      :ets.insert(@table, {:blocked_until, until})

      Logger.warning(
        "Binance rate limit: HTTP #{status}; refusing every call for #{until - now_ms} ms " <>
          "(until #{DateTime.from_unix!(until, :millisecond)})"
      )
    end
  end

  defp retry_after_ms(headers, now_ms) do
    case header(headers, "retry-after") do
      nil -> nil
      v -> now_ms + parse_int(v) * 1_000 + 500
    end
  end

  defp banned_until_ms(%{"msg" => msg}) when is_binary(msg), do: banned_until_ms(msg)

  defp banned_until_ms(msg) when is_binary(msg) do
    case Regex.run(~r/banned until (\d+)/, msg) do
      [_, ms] -> String.to_integer(ms) + 1_000
      _ -> nil
    end
  end

  defp banned_until_ms(_), do: nil

  defp next_minute_ms(now_ms), do: now_ms + ms_to_next_minute(now_ms)
  defp ms_to_next_minute(now_ms), do: @minute_ms - rem(now_ms, @minute_ms) + 500

  defp header(headers, name) do
    Enum.find_value(headers, fn {k, v} -> if String.downcase(k) == name, do: v end)
  end

  defp parse_int(v) do
    case Integer.parse(String.trim(v)) do
      {n, _} -> n
      :error -> 0
    end
  end

  defp lookup(key) do
    case :ets.lookup(@table, key) do
      [{:used, used, at}] -> {used, at}
      [{^key, v}] -> v
      _ -> nil
    end
  end

  defp table?, do: :ets.whereis(@table) != :undefined
  defp now_ms, do: System.system_time(:millisecond)
end
