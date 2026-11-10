defmodule FluxTrader.Account.Sync do
  @moduledoc """
  Copies the shared account's fills and income from Binance into `account_fills` /
  `account_income`, every 10 minutes and on demand (the account page's
  Refresh). Read-only: only signed GETs.

  ## Calls

    1. `/fapi/v1/income` from the newest stored row (or `@history_start`) in 7-day windows —
       every income type; the commission rows say which symbols traded.
    2. `/fapi/v1/userTrades` per symbol whose newest COMMISSION row is newer than its newest
       stored fill — usually none or one symbol per run.
    3. `/fapi/v2/account` positions, compared against the open deals rebuilt from the fills: a
       mismatch means the history does not reach back to the position's opening fill, and the
       page says so rather than showing a wrong deal.

  Rows are inserted with `on_conflict: :nothing`, so overlapping windows are harmless.
  `@history_start` must predate the opening fill of every position open on the day the page
  started: the manual ADA long was opened 2026-06-05 (verified 2026-11-10 — fills from 05-15
  rebuild the exchange's 2495 exactly; from 10-01 only 1169). `userTrades` serves the last six
  months only, so a first sync is clamped to 179 days back; rows once stored stay.
  """
  use GenServer
  require Logger

  import Ecto.Query

  alias FluxTrader.Account.{Fill, Income, Stats}
  alias FluxTrader.Binance.Client
  alias FluxTrader.Repo

  @history_start ~U[2026-05-15 00:00:00Z]
  @max_back_ms 179 * 24 * 3600 * 1000
  @window_ms 7 * 24 * 3600 * 1000
  @interval_ms 10 * 60_000
  @topic "account:synced"

  def topic, do: @topic
  def history_start, do: @history_start

  def start_link(opts \\ []), do: GenServer.start_link(__MODULE__, opts, name: __MODULE__)

  @doc "The last run's outcome, or `%{status: :not_running}` when the worker is off."
  def status do
    GenServer.call(__MODULE__, :status, 2_000)
  catch
    :exit, _ -> %{status: :not_running}
  end

  @doc "Run now (async). The page hears `{:account_synced, status}` on `topic/0` when done."
  def refresh, do: GenServer.cast(__MODULE__, :sync)

  @impl true
  def init(opts) do
    state = %{
      get: Keyword.get(opts, :get, &Client.signed_get/2),
      status: :pending,
      last_ok_at: nil,
      last_error: nil,
      mismatches: []
    }

    if Keyword.get(opts, :autostart, true), do: Process.send_after(self(), :tick, 30_000)
    {:ok, state}
  end

  @impl true
  def handle_call(:status, _from, state) do
    {:reply, Map.take(state, [:status, :last_ok_at, :last_error, :mismatches]), state}
  end

  def handle_call(:sync_now, _from, state) do
    state = run(state)
    {:reply, Map.take(state, [:status, :last_ok_at, :last_error, :mismatches]), state}
  end

  @impl true
  def handle_cast(:sync, state), do: {:noreply, run(state)}

  @impl true
  def handle_info(:tick, state) do
    Process.send_after(self(), :tick, @interval_ms)
    {:noreply, run(state)}
  end

  def handle_info(_, state), do: {:noreply, state}

  defp run(state) do
    state =
      cond do
        not Client.credentials?() ->
          %{state | status: :missing_credentials}

        Client.testnet?() ->
          %{state | status: :testnet}

        true ->
          case sync(state.get) do
            {:ok, mismatches} ->
              %{state | status: :ok, last_ok_at: DateTime.utc_now(), last_error: nil, mismatches: mismatches}

            {:error, reason} ->
              Logger.warning("[ACCOUNT] sync failed: #{inspect(reason)}")
              %{state | status: :error, last_error: inspect(reason)}
          end
      end

    Phoenix.PubSub.broadcast(FluxTrader.PubSub, @topic, {:account_synced, state.status})
    state
  end

  @doc "One full pass with `get` (`(path, params) -> {:ok, body} | {:error, _}`)."
  def sync(get) do
    now_ms = System.system_time(:millisecond)

    with :ok <- sync_income(get, now_ms),
         :ok <- sync_fills(get, now_ms),
         {:ok, positions} <- positions(get) do
      {:ok, mismatches(positions)}
    end
  end

  defp sync_income(get, now_ms) do
    from_ms =
      case Repo.one(from(i in Income, select: max(i.time))) do
        nil -> DateTime.to_unix(@history_start, :millisecond)
        t -> DateTime.to_unix(t, :millisecond) - 3_600_000
      end

    windows(get, "/fapi/v1/income", [], from_ms, now_ms, &insert_income/1)
  end

  defp sync_fills(get, now_ms) do
    last_commission =
      from(i in Income,
        where: i.income_type == "COMMISSION" and i.symbol != "",
        group_by: i.symbol,
        select: {i.symbol, max(i.time)}
      )
      |> Repo.all()

    last_fill = from(f in Fill, group_by: f.symbol, select: {f.symbol, max(f.time)}) |> Repo.all() |> Map.new()

    Enum.reduce_while(last_commission, :ok, fn {symbol, c_at}, :ok ->
      f_at = last_fill[symbol]

      if f_at != nil and DateTime.compare(c_at, f_at) != :gt do
        {:cont, :ok}
      else
        from_ms =
          if f_at,
            do: DateTime.to_unix(f_at, :millisecond) - 60_000,
            else: max(DateTime.to_unix(@history_start, :millisecond), now_ms - @max_back_ms)

        case windows(get, "/fapi/v1/userTrades", [symbol: symbol], from_ms, now_ms, &insert_fills/1) do
          :ok -> {:cont, :ok}
          err -> {:halt, err}
        end
      end
    end)
  end

  # 7-day windows (userTrades refuses longer); inside a window, page by the last row's time
  # while a page comes back full.
  defp windows(_get, _path, _params, from_ms, now_ms, _insert) when from_ms >= now_ms, do: :ok

  defp windows(get, path, params, from_ms, now_ms, insert) do
    to_ms = min(from_ms + @window_ms - 1, now_ms)

    case page(get, path, params, from_ms, to_ms, insert) do
      :ok -> windows(get, path, params, to_ms + 1, now_ms, insert)
      err -> err
    end
  end

  defp page(get, path, params, from_ms, to_ms, insert) do
    case get.(path, params ++ [startTime: from_ms, endTime: to_ms, limit: 1000]) do
      {:ok, rows} when is_list(rows) ->
        insert.(rows)

        if length(rows) >= 1000 do
          last = rows |> Enum.map(& &1["time"]) |> Enum.max()
          next = if last > from_ms, do: last, else: from_ms + 1
          page(get, path, params, next, to_ms, insert)
        else
          :ok
        end

      {:ok, other} ->
        {:error, {path, :unexpected, other}}

      {:error, reason} ->
        {:error, {path, reason}}
    end
  end

  defp insert_income(rows) do
    now = NaiveDateTime.utc_now() |> NaiveDateTime.truncate(:second)

    entries =
      for r <- rows do
        %{
          symbol: r["symbol"] || "",
          income_type: r["incomeType"],
          income: num(r["income"]),
          asset: r["asset"],
          tran_id: int(r["tranId"]),
          trade_id: blank_nil(r["tradeId"]),
          time: ms(r["time"]),
          inserted_at: now,
          updated_at: now
        }
      end

    Repo.insert_all(Income, entries,
      on_conflict: :nothing,
      conflict_target: [:tran_id, :income_type, :symbol, :time]
    )
  end

  defp insert_fills(rows) do
    now = NaiveDateTime.utc_now() |> NaiveDateTime.truncate(:second)

    entries =
      for r <- rows do
        %{
          symbol: r["symbol"],
          trade_id: int(r["id"]),
          order_id: int(r["orderId"]),
          side: r["side"],
          qty: num(r["qty"]),
          price: num(r["price"]),
          realized_pnl: num(r["realizedPnl"]),
          commission: num(r["commission"]),
          commission_asset: r["commissionAsset"],
          maker: r["maker"],
          time: ms(r["time"]),
          inserted_at: now,
          updated_at: now
        }
      end

    Repo.insert_all(Fill, entries, on_conflict: :nothing, conflict_target: [:symbol, :trade_id])
  end

  defp positions(get) do
    case get.("/fapi/v2/account", []) do
      {:ok, %{"positions" => ps}} ->
        {:ok,
         for(p <- ps, (q = num(p["positionAmt"])) != 0.0, into: %{}, do: {p["symbol"], q})}

      {:ok, other} ->
        {:error, {:account, :unexpected, other}}

      {:error, reason} ->
        {:error, {:account, reason}}
    end
  end

  @doc "Symbols where the exchange's position and the rebuilt open deal disagree."
  def mismatches(positions, deals \\ nil) do
    open =
      (deals || Stats.deals())
      |> Enum.filter(&is_nil(&1.closed_at))
      |> Map.new(&{&1.symbol, &1.qty})

    (Map.keys(positions) ++ Map.keys(open))
    |> Enum.uniq()
    |> Enum.reject(fn s -> abs(Map.get(positions, s, 0.0) - Map.get(open, s, 0.0)) < 1.0e-9 end)
    |> Enum.sort()
    |> Enum.map(&%{symbol: &1, exchange: Map.get(positions, &1, 0.0), rebuilt: Map.get(open, &1, 0.0)})
  end

  defp ms(t) when is_integer(t), do: DateTime.from_unix!(t * 1000, :microsecond)

  defp num(x) when is_number(x), do: x * 1.0

  defp num(x) when is_binary(x) do
    case Float.parse(x) do
      {f, _} -> f
      :error -> 0.0
    end
  end

  defp num(_), do: 0.0

  defp int(x) when is_integer(x), do: x
  defp int(x) when is_binary(x), do: String.to_integer(x)

  defp blank_nil(nil), do: nil
  defp blank_nil(""), do: nil
  defp blank_nil(x), do: to_string(x)
end
