defmodule FluxTrader.Trading.Executor do
  @moduledoc """
  The order path. **It crosses the spread, and that is the whole design.**

  ## Why there are no limit orders in this file

  M3-4 measured both arms on 23 days of order-book history (`docs/M3_4_RESULTS.md`). Resting
  a limit order looks 3.60 bps cheaper round trip on the fee arithmetic — but the
  adverse-selection panel is negative in **16 of 16** (pair, direction) cells: a resting buy
  fills *because* the price came down through it, and then keeps going. The touch spread on
  BTC is 0.01 bps, so there is almost no spread to capture in the first place; what the
  maker arm collects in fees it hands straight back in the price path.

  So there is no queue model here, no fill probability, no chase logic and no partial-fill
  bookkeeping. M3_PLAN §0.8 item 3 states the consequence plainly: this is days of work M3-5
  does not have to do. If someone later wants the maker arm, that is a new study with a new
  protocol, not an edit to this module.

  ## Modes

    * `simulation` — the paper book. Entries and exits are ledger rows priced at the last
      traded price and charged M3-4's **measured per-pair** crossing cost. This is what the
      A/B runs on and it is the default.
    * `signal` — log the intent, book nothing.
    * `manual` — hold for approval.
    * `auto` — a real `MARKET` order on Binance USDⓈ-M, signed, reconciled against the
      exchange's fill, and braked. Crossing, because that is what the strategy was scored
      assuming. The row it writes carries the exchange's `avgPrice` and `executedQty`,
      `fill_source: "exchange"`, and is charged the two taker fees only (slippage is already
      inside a real fill price — see `ExecCost.fee_only_round_trip_bps/0`). The order logic
      itself is `Trading.ExchangeOrders`; this module owns the mode, the ledger row and the
      risk bookkeeping.

  ## What `auto` requires, and what happens without it

  Credentials (`BINANCE_API_KEY` / `BINANCE_API_SECRET`) and a trading host
  (`Binance.Client.trade_url/0`; `BINANCE_TESTNET=true` for the testnet). If the mode is
  `auto` and the credentials are missing, this process **refuses the mode and runs as
  `simulation`**, logs it as an error at boot, and reports `auto_refused` on `status/0` and
  `/api/health`. Crashing the supervisor instead would take the collector down with it, and
  the collector must not depend on a trading credential.

  ## One deviation from the scored policy, stated out loud

  `RiskManager` attaches a stop and a target to every approved order. The M3-2 policy has
  **neither** — it was scored on a fixed four-hour hold and nothing else, and a barrier exit
  backtested against a fixed-horizon return is exactly the policy mismatch C4b was filed
  for. The paper arms therefore ignore both and close on the timer. On the `auto` path they
  are placed on the exchange as a catastrophe brake (REAL_MONEY_TRACK Q2, decided
  2026-09-10: **keep**). M3-0b priced the brake at ~10.5 gross bps a trade on the fixed-hold
  backtest — the premium, not the insurance — and a brake fill is booked with
  `exit_reason: "stop"` / `"target"` so the forward ledger can separate the two exits.
  """
  use GenServer
  require Logger

  alias FluxTrader.Binance.{Client, Trade}
  alias FluxTrader.Trading.{ExchangeOrders, ExecCost, Ledger, PaperTrade, RiskManager}

  # The A/B's control arm is a measurement ledger and must never reach the exchange: it
  # exists to say what M2's raw gate would have earned, not to trade it.
  @paper_only_arms ["flat_size"]

  def start_link(opts), do: GenServer.start_link(__MODULE__, opts, name: __MODULE__)

  @doc """
  Open a position on `arm` from an approved order.

  The policy arm reaches this only after `RiskManager.check/1` has approved it — that is
  M3_PLAN §6's last exit criterion, and `risk_manager_test.exs` pins it.
  """
  def open(arm, decision, order \\ %{}) do
    GenServer.call(__MODULE__, {:open, arm, decision, order}, 30_000)
  end

  @doc "Close a position at `exit_price` and book its realised P&L."
  def close(%PaperTrade{} = trade, exit_price) do
    GenServer.call(__MODULE__, {:close, trade, exit_price}, 30_000)
  end

  @doc "Open positions, shaped for the dashboard. `pnl` is unrealised **net bps**, not currency."
  def get_positions do
    GenServer.call(__MODULE__, :get_positions, 10_000)
  end

  @doc "The mode in force — `simulation` if `auto` was requested but refused."
  def mode, do: GenServer.call(__MODULE__, :mode)

  @doc "Mode, what was requested, why `auto` was refused if it was, and where orders go."
  def status, do: GenServer.call(__MODULE__, :status)

  @doc """
  A brake order filled on the exchange — reported by `Binance.UserStream`. Books the close
  on the row that holds `order_id` as its stop or target, cancels the sibling brake, and
  settles the risk manager. A fill on an order no open row knows is logged and ignored.
  """
  def brake_filled(order_id, avg_price) when is_integer(order_id) and is_number(avg_price),
    do: GenServer.call(__MODULE__, {:brake_filled, order_id, avg_price}, 30_000)

  @impl true
  def init(_opts) do
    config = Application.get_env(:fluxtrader, :trading, [])
    requested = Keyword.get(config, :mode, "simulation")
    {mode, refused} = resolve_mode(requested)

    Logger.info("Executor starting in #{mode} mode (crossing only; no limit orders — M3-4)")

    if mode == "auto" do
      Logger.warning(
        "[AUTO] REAL ORDERS ARE LIVE against #{Client.trade_url()}" <>
          if(Client.testnet?(), do: " (TESTNET)", else: " (PRODUCTION)")
      )
    end

    {:ok,
     %{
       mode: mode,
       requested_mode: requested,
       auto_refused: refused,
       marks: %{},
       client: Trade.impl(),
       # Symbol filters from the trading host, fetched on the first real order and kept.
       filters: nil
     }}
  end

  # `auto` needs a credential. Without one the mode is refused rather than the process
  # crashed: this supervisor also runs the collector, and a missing trading key must not
  # be able to stop data collection.
  defp resolve_mode("auto") do
    if Client.credentials?() do
      {"auto", nil}
    else
      Logger.error(
        "TRADING_MODE=auto but BINANCE_API_KEY / BINANCE_API_SECRET are not set — " <>
          "REFUSING auto and running as simulation. Nothing will reach the exchange."
      )

      {"simulation", :missing_credentials}
    end
  end

  defp resolve_mode(mode), do: {mode, nil}

  @impl true
  def handle_call(:mode, _from, state), do: {:reply, state.mode, state}

  def handle_call(:status, _from, state) do
    {:reply,
     %{
       mode: state.mode,
       requested_mode: state.requested_mode,
       auto_refused: state.auto_refused,
       live_orders: state.mode == "auto",
       trade_url: Client.trade_url(),
       testnet: Client.testnet?(),
       credentials_present: Client.credentials?(),
       filters_loaded: state.filters != nil
     }, state}
  end

  def handle_call({:open, arm, decision, order}, _from, state) do
    {reply, state} = do_open(state.mode, arm, decision, order, state)
    {:reply, reply, state}
  end

  def handle_call({:close, trade, exit_price}, _from, state) do
    {:reply, do_close(state.mode, trade, exit_price, state), state}
  end

  def handle_call({:brake_filled, order_id, avg_price}, _from, state) do
    {:reply, do_brake_filled(order_id, avg_price, state), state}
  end

  def handle_call(:get_positions, _from, state) do
    positions =
      Enum.flat_map(PaperTrade.arms(), fn arm ->
        arm
        |> Ledger.open_trades()
        |> Enum.map(&to_display(&1, state.marks))
      end)

    {:reply, positions, state}
  end

  @impl true
  def handle_cast({:mark, pair, price}, state) do
    {:noreply, %{state | marks: Map.put(state.marks, pair, price)}}
  end

  @doc "Remember the last seen price for a pair, so open positions can be marked."
  def mark(pair, price) when is_number(price),
    do: GenServer.cast(__MODULE__, {:mark, pair, price})

  # ------------------------------------------------------------------ open

  defp do_open(mode, arm, decision, _order, state) when mode in ["simulation", "signal", "manual"] do
    # Every non-auto mode books the same paper row. `signal` and `manual` differ from
    # `simulation` in what they do about a REAL order, and none of them places one — the
    # measurement must keep running regardless, because the point of the forward test is to
    # accumulate independent days (§0.5.4) and a mode switch should not silence it.
    {paper_open(mode, arm, decision), state}
  end

  defp do_open("auto", arm, decision, _order, state) when arm in @paper_only_arms do
    # Never route the control arm to the exchange, whatever the mode says.
    {paper_open("simulation", arm, decision), state}
  end

  defp do_open("auto", arm, decision, order, state) do
    with {:ok, filters, state} <- ensure_filters(state),
         req = %{
           symbol: decision.pair,
           side: side_word(decision.side),
           quantity: order[:quantity],
           price: decision.entry_price,
           leverage: order[:leverage],
           stop_loss: order[:stop_loss],
           take_profit: order[:take_profit]
         },
         {:ok, fill} <- ExchangeOrders.open(state.client, filters, req) do
      Logger.info(
        "[AUTO] OPEN #{arm} #{req.side} #{decision.pair} filled qty=#{fill.executed_qty} " <>
          "@ #{fmt(fill.avg_price)} (signal price #{fmt(decision.entry_price)}) " <>
          "order=#{fill.order_id} stop=#{inspect(fill.stop_order_id)} " <>
          "target=#{inspect(fill.target_order_id)}"
      )

      # The row is written from what the exchange did, not from what was asked: the fill
      # price, the filled quantity, and the fee-only cost, because slippage is already in
      # the price. It is still the ledger the A/B and every M3_PROTOCOL §4 metric read.
      overrides = %{
        entry_price: fill.avg_price,
        quantity: fill.executed_qty,
        notional: fill.avg_price * fill.executed_qty,
        cost_bps: ExecCost.fee_only_round_trip_bps(),
        fill_source: "exchange",
        entry_order_id: fill.order_id,
        stop_order_id: fill.stop_order_id,
        target_order_id: fill.target_order_id
      }

      case Ledger.open_trade(arm, decision, overrides) do
        {:ok, trade} ->
          {{:ok, trade}, state}

        {:error, changeset} ->
          # A real position with no row is the one state this module must never leave
          # behind: the ledger would be fiction and the timer could never close it. Unwind.
          Logger.error(
            "[AUTO] filled #{decision.pair} but the ledger refused the row " <>
              "(#{inspect(changeset.errors)}) — CLOSING the position immediately"
          )

          unwind(state.client, decision.pair, side_word(-decision.side), fill)
          {{:error, changeset}, state}
      end
    else
      {:error, reason} ->
        Logger.error("[AUTO] order failed for #{decision.pair}: #{inspect(reason)}")
        {{:error, reason}, state}

      {:error, reason, state} ->
        Logger.error("[AUTO] order failed for #{decision.pair}: #{inspect(reason)}")
        {{:error, reason}, state}
    end
  end

  defp paper_open(mode, arm, decision) do
    case Ledger.open_trade(arm, decision) do
      {:ok, trade} ->
        {tag, cost} = ExecCost.round_trip_bps(decision.pair)

        Logger.info(
          "[#{String.upcase(mode)}] OPEN #{arm} #{side_word(decision.side)} #{decision.pair} " <>
            "@ #{fmt(decision.entry_price)} size=#{fmt(decision.size)} " <>
            "conf=#{fmt(decision.confidence)} cost=#{fmt(cost)}bps(#{tag}) " <>
            "exit_after=#{decision.exit_after_ts}"
        )

        {:ok, trade}

      {:error, changeset} ->
        # The commonest cause is the partial unique index refusing a second open position on
        # a pair, which is invariant 2 doing its job rather than a fault.
        Logger.debug("open #{arm} #{decision.pair} refused: #{inspect(changeset.errors)}")
        {:error, changeset}
    end
  end

  defp ensure_filters(%{filters: nil} = state) do
    case ExchangeOrders.load_filters(state.client) do
      {:ok, filters} -> {:ok, filters, %{state | filters: filters}}
      {:error, reason} -> {:error, reason, state}
    end
  end

  defp ensure_filters(%{filters: filters} = state), do: {:ok, filters, state}

  defp unwind(client, symbol, closing_side, fill) do
    req = %{
      symbol: symbol,
      side: closing_side,
      quantity: fill.executed_qty,
      stop_order_id: fill.stop_order_id,
      target_order_id: fill.target_order_id
    }

    case ExchangeOrders.close(client, req) do
      {:ok, _} -> Logger.warning("[AUTO] unwound #{symbol}")
      {:error, reason} -> Logger.error("[AUTO] UNWIND FAILED on #{symbol}: #{inspect(reason)} — MANUAL ACTION")
    end
  end

  # ------------------------------------------------------------------ close

  defp do_close("auto", %PaperTrade{arm: arm} = trade, exit_price, state)
       when arm in @paper_only_arms,
       do: do_close("simulation", trade, exit_price, state)

  defp do_close("auto", %PaperTrade{fill_source: "exchange"} = trade, mark_price, state) do
    # Re-read first: a brake may have filled and been booked by the user-data stream
    # between the due-list read and now, and a closed row must not be booked twice.
    case Ledger.reload(trade) do
      %PaperTrade{status: "open"} = trade ->
        req = %{
          symbol: trade.pair,
          side: side_word(-trade.side),
          quantity: trade.quantity,
          stop_order_id: trade.stop_order_id,
          target_order_id: trade.target_order_id
        }

        case ExchangeOrders.close(state.client, req) do
          {:ok, fill} ->
            book_close("AUTO", trade, fill.avg_price, %{
              exit_reason: fill.exit_reason,
              exit_order_id: fill.order_id
            })

          {:error, :position_missing} ->
            # The exchange has no position and no brake reports a fill: a liquidation or a
            # manual close. The row cannot stay open — it would hold a risk slot forever —
            # so it is booked at the mark with a reason that says the number is not a fill.
            Logger.error(
              "[AUTO] #{trade.pair}: no position on the exchange and no brake filled — " <>
                "booking the row at the mark #{fmt(mark_price)} as position_missing"
            )

            book_close("AUTO", trade, mark_price, %{exit_reason: "position_missing"})

          {:error, reason} ->
            Logger.error("[AUTO] close failed for #{trade.pair}: #{inspect(reason)}")
            {:error, reason}
        end

      _ ->
        {:error, :already_closed}
    end
  end

  # A paper row on the auto path (opened before the mode was switched) closes as paper.
  defp do_close("auto", %PaperTrade{} = trade, exit_price, state),
    do: do_close("simulation", trade, exit_price, state)

  defp do_close(mode, %PaperTrade{} = trade, exit_price, _state) do
    book_close(String.upcase(mode), trade, exit_price, %{})
  end

  defp book_close(label, trade, exit_price, overrides) do
    case Ledger.close_trade(trade, exit_price, DateTime.utc_now(), overrides) do
      {:ok, closed} ->
        Logger.info(
          "[#{label}] CLOSE #{closed.arm} #{closed.pair} @ #{fmt(exit_price)} " <>
            "gross=#{fmt(closed.gross_bps)}bps cost=#{fmt(closed.cost_bps)}bps " <>
            "net=#{fmt(closed.net_bps)}bps reason=#{closed.exit_reason}"
        )

        {:ok, closed}

      other ->
        other
    end
  end

  # ------------------------------------------------------------------ brake fills

  defp do_brake_filled(order_id, avg_price, state) do
    case Ledger.open_trade_by_brake(order_id) do
      nil ->
        Logger.warning("[AUTO] brake fill on order #{order_id} matches no open row — ignored")
        {:error, :unknown_order}

      %PaperTrade{} = trade ->
        reason = if trade.stop_order_id == order_id, do: "stop", else: "target"

        Logger.warning(
          "[AUTO] BRAKE FIRED: #{reason} on #{trade.pair} @ #{fmt(avg_price)} (order #{order_id})"
        )

        # The sibling brake is still resting and would act on the NEXT position on this
        # symbol if it were left there.
        _ = state.client.cancel_all_open_orders(trade.pair)

        case book_close("AUTO", trade, avg_price, %{exit_reason: reason, exit_order_id: order_id}) do
          {:ok, closed} ->
            RiskManager.record_closed_trade(closed)
            {:ok, closed}

          other ->
            other
        end
    end
  end

  # ------------------------------------------------------------------ helpers

  defp to_display(%PaperTrade{} = t, marks) do
    mark = Map.get(marks, t.pair)

    unrealised =
      if mark && t.entry_price > 0 do
        t.side * (mark / t.entry_price - 1.0) * t.size * 1.0e4 - (t.cost_bps || 0.0) * t.size
      else
        0.0
      end

    %{
      id: t.id,
      arm: t.arm,
      symbol: t.pair,
      side: side_word(t.side),
      entry_price: t.entry_price,
      size: t.size,
      quantity: t.size,
      status: :open,
      opened_at: t.entry_ts,
      exit_after: t.exit_after_ts,
      # Unrealised net bps at the last seen price, not currency. 0.0 means unmarked.
      pnl: unrealised
    }
  end

  defp side_word(side) when side > 0, do: "BUY"
  defp side_word(side) when side < 0, do: "SELL"

  defp fmt(nil), do: "-"
  defp fmt(x) when is_float(x), do: :erlang.float_to_binary(x, decimals: 4)
  defp fmt(x), do: to_string(x)
end
