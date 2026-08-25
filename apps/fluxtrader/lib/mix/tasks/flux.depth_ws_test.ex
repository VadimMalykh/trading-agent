defmodule Mix.Tasks.Flux.DepthWsTest do
  @shortdoc "Probe whether Binance WS market-data frames reach this host (B4.3)"

  @moduledoc """
  B4.3 (docs/BOOK_ERA_PLAN.md §2) — a connectivity test, not a project.

  ## The question

  The collector polls `/fapi/v1/depth` every 5s, which is the fidelity ceiling for
  any short-horizon (1m/5m) work: intra-5s book dynamics are simply unseen. The fix
  is the `@depth` diff WebSocket stream. But `!forceOrder@arr` already taught us
  that Binance gates the WS **data plane** from datacenter egress — the connection
  upgrades and the SUBSCRIBE is acked, and then zero market-data frames ever
  arrive, which is why `liquidations` has 0 rows. Before anyone designs around
  `@depth`, we need to know whether it is gated the same way *from the VM that
  would actually consume it*.

  ## How it answers it

  One connection, three subscriptions, counted by the payload's `"e"` field:

    * `<sym>@depth@100ms` -> `depthUpdate`  — the stream we actually want
    * `<sym>@aggTrade`    -> `aggTrade`     — CONTROL: is *any* market data allowed?
    * `!forceOrder@arr`   -> `forceOrder`   — known-blocked reference point

  The control is what makes the result interpretable. "No depth frames" on its own
  cannot distinguish "@depth is gated" from "this host gets no WS data at all", and
  those imply completely different next steps.

  Frames are counted, not stored. Nothing is written to the database.

  ## Verdicts

    * `DEPTH_OK`        — depth frames arrived. `@depth` is viable from this host.
    * `DEPTH_BLOCKED`   — control frames arrived but no depth frames. `@depth`
                          specifically is gated.
    * `WS_BLOCKED`      — upgraded and subscribed, but no market data of any kind.
                          Same failure as `!forceOrder@arr`; run from non-datacenter
                          egress before concluding anything about `@depth` itself.
    * `CONNECT_FAILED`  — never upgraded. A network/TLS problem, not a gating one.

  Exit status is always 0: "blocked" is a valid answer to the question, not a
  failure of the test.

  ## Usage

      mix flux.depth_ws_test
      mix flux.depth_ws_test --symbol ethusdt --seconds 120
      mix flux.depth_ws_test --streams btcusdt@depth20@100ms,btcusdt@aggTrade

  Run it on the always-on VM (that is the egress that matters) via
  `scripts/gcp_depth_ws_test.sh`.
  """

  use Mix.Task

  @host ~c"fstream.binance.com"
  @port 443
  # Bare /ws + explicit SUBSCRIBE, matching FluxTrader.Binance.WebSocket. Do NOT
  # switch to /stream?streams=... here: embedding streams in the path is exactly
  # what silently yielded no frames on some edges, and a probe that differs from
  # the real consumer measures the wrong thing.
  @path ~c"/ws"
  @default_seconds 60
  @connect_timeout_ms 15_000

  @impl Mix.Task
  def run(argv) do
    {opts, _, _} =
      OptionParser.parse(argv,
        strict: [symbol: :string, seconds: :integer, streams: :string]
      )

    symbol = opts |> Keyword.get(:symbol, "btcusdt") |> String.downcase()
    seconds = Keyword.get(opts, :seconds, @default_seconds)

    streams =
      case Keyword.get(opts, :streams) do
        nil -> ["#{symbol}@depth@100ms", "#{symbol}@aggTrade", "!forceOrder@arr"]
        s -> s |> String.split(",", trim: true) |> Enum.map(&String.trim/1)
      end

    # Deliberately no `app.start`: on the always-on VM this runs inside the same
    # container as the live collector, and booting a second FluxTrader.Application
    # would collide on every named process. Only the WS transport is needed.
    {:ok, _} = Application.ensure_all_started(:gun)

    IO.puts("host       : wss://#{@host}#{@path}")
    IO.puts("streams    : #{Enum.join(streams, ", ")}")
    IO.puts("listen for : #{seconds}s")
    IO.puts("")

    probe(streams, seconds) |> report()
  end

  defp probe(streams, seconds) do
    with {:ok, conn} <- open(),
         :ok <- await_up(conn),
         {:ok, stream_ref} <- upgrade(conn) do
      sub = Jason.encode!(%{"method" => "SUBSCRIBE", "params" => streams, "id" => 1})
      :gun.ws_send(conn, stream_ref, {:text, sub})

      started = now_ms()
      result = collect(conn, stream_ref, started + seconds * 1000, started, %{}, %{}, false)
      :gun.close(conn)
      result
    else
      {:error, reason} -> {:connect_failed, reason}
    end
  end

  defp open do
    # retry: 0 — unlike the persistent consumer, a probe must NOT silently
    # reconnect mid-window: a reconnect restarts the subscription and the frame
    # counts would no longer describe a single continuous listen. (A TLS/DNS
    # failure still surfaces as a bare `:timeout` from await_up; the specific
    # cause is in the log above the verdict.)
    case :gun.open(@host, @port, %{protocols: [:http], transport: :tls, retry: 0}) do
      {:ok, conn} -> {:ok, conn}
      {:error, reason} -> {:error, reason}
    end
  end

  defp await_up(conn) do
    case :gun.await_up(conn, @connect_timeout_ms) do
      {:ok, _proto} -> :ok
      {:error, reason} -> {:error, {:no_connection, reason}}
    end
  end

  defp upgrade(conn) do
    stream_ref = :gun.ws_upgrade(conn, @path)

    receive do
      {:gun_upgrade, ^conn, ^stream_ref, _protos, _headers} -> {:ok, stream_ref}
      {:gun_response, ^conn, _, _, status, _} -> {:error, {:upgrade_rejected, status}}
      {:gun_error, ^conn, _, reason} -> {:error, {:upgrade_error, reason}}
    after
      @connect_timeout_ms -> {:error, :upgrade_timeout}
    end
  end

  # Counts frames per event type and records how long each type took to first
  # appear — a stream that only starts after 30s looks identical to a blocked one
  # in a short probe, so the latency is part of the evidence.
  defp collect(conn, stream_ref, deadline_ms, started_ms, counts, first_ms, acked) do
    remaining = deadline_ms - now_ms()

    if remaining <= 0 do
      {:ok, counts, first_ms, acked}
    else
      receive do
        {:gun_ws, ^conn, ^stream_ref, {:text, msg}} ->
          {counts, first_ms, acked} = classify(msg, started_ms, counts, first_ms, acked)
          collect(conn, stream_ref, deadline_ms, started_ms, counts, first_ms, acked)

        {:gun_ws, ^conn, ^stream_ref, {:close, code, reason}} ->
          {:closed, code, reason, counts, first_ms, acked}

        {:gun_ws, ^conn, ^stream_ref, :close} ->
          {:closed, :normal, "", counts, first_ms, acked}

        {:gun_down, ^conn, _proto, reason, _killed} ->
          {:closed, :gun_down, reason, counts, first_ms, acked}

        _other ->
          collect(conn, stream_ref, deadline_ms, started_ms, counts, first_ms, acked)
      after
        remaining -> {:ok, counts, first_ms, acked}
      end
    end
  end

  defp classify(msg, started_ms, counts, first_ms, acked) do
    case Jason.decode(msg) do
      {:ok, %{"result" => _, "id" => _}} ->
        # SUBSCRIBE ack. Getting this while receiving zero data frames is the
        # exact signature of the liquidation-stream block.
        {counts, first_ms, true}

      {:ok, %{"e" => event}} ->
        {bump(counts, event), Map.put_new(first_ms, event, now_ms() - started_ms), acked}

      {:ok, %{"stream" => stream}} ->
        {bump(counts, stream), Map.put_new(first_ms, stream, now_ms() - started_ms), acked}

      _ ->
        {bump(counts, "unparsed"), first_ms, acked}
    end
  end

  defp bump(counts, key), do: Map.update(counts, key, 1, &(&1 + 1))

  defp report({:connect_failed, reason}) do
    IO.puts("connection : FAILED (#{inspect(reason)})")
    IO.puts("")
    IO.puts("VERDICT: CONNECT_FAILED")
    IO.puts("This is a network/TLS problem, not a gating one. Re-run before drawing")
    IO.puts("any conclusion about @depth.")
  end

  defp report({:closed, code, reason, counts, first_ms, acked}) do
    IO.puts("connection : CLOSED EARLY (#{inspect(code)} #{inspect(reason)})")
    print_counts(counts, first_ms, acked)
    verdict(counts)
  end

  defp report({:ok, counts, first_ms, acked}) do
    IO.puts("connection : upgraded, stayed open for the full window")
    print_counts(counts, first_ms, acked)
    verdict(counts)
  end

  defp print_counts(counts, first_ms, acked) do
    IO.puts("subscribe  : #{if acked, do: "ACKed by the exchange", else: "NO ack seen"}")
    IO.puts("")
    IO.puts(String.pad_trailing("event", 16) <> String.pad_leading("frames", 8) <> "   first frame")

    if counts == %{} do
      IO.puts("(no frames at all)")
    else
      counts
      |> Enum.sort_by(fn {_k, v} -> -v end)
      |> Enum.each(fn {event, n} ->
        first =
          case Map.get(first_ms, event) do
            nil -> "-"
            ms -> "#{ms}ms"
          end

        IO.puts(String.pad_trailing(event, 16) <> String.pad_leading(to_string(n), 8) <> "   " <> first)
      end)
    end

    IO.puts("")
  end

  defp verdict(counts) do
    depth = Map.get(counts, "depthUpdate", 0)
    control = Map.get(counts, "aggTrade", 0)

    cond do
      depth > 0 ->
        IO.puts("VERDICT: DEPTH_OK")
        IO.puts("@depth frames reach this host (#{depth} in the window). The 5s REST")
        IO.puts("cadence is not a hard ceiling — a WS depth consumer is worth building.")

      control > 0 ->
        IO.puts("VERDICT: DEPTH_BLOCKED")
        IO.puts("Market data flows (#{control} aggTrade frames) but no depthUpdate frames.")
        IO.puts("@depth is gated specifically. Do not design around it.")

      true ->
        IO.puts("VERDICT: WS_BLOCKED")
        IO.puts("No market-data frames of any kind — the same failure that leaves")
        IO.puts("`liquidations` at 0 rows. Before concluding anything about @depth,")
        IO.puts("re-run from non-datacenter egress: this measures the host, not the stream.")
    end
  end

  defp now_ms, do: System.monotonic_time(:millisecond)
end
