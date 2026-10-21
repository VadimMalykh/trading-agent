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

  ## The pilot's maker path (M2, BOOK_WAVE2_PLAN §M2, built 2026-10-21)

  With `LIVE_PILOT_MAKER_PATH=true` the `live` arm — and only it — enters and exits through
  `ExchangeOrders`' maker path: a post-only limit at the touch for 60 s, then the remainder
  crossed. The row is written when the entry is **placed** (`entry_order_type: "maker_resting"`,
  priced at the rest) so the pilot's slot is held and a restart can find the order; a task
  under `FluxTrader.TaskSupervisor` waits out the rest and reports back through
  `entry_settled/2`, which rewrites the row from the realised leg (VWAP, quantity, type, wait,
  fee, the touch) and attaches the brakes to the filled quantity — so for at most 60 s a
  position may stand unbraked, said so here. The exit mirrors it: `close/2` on such a row
  cancels the brakes, rests a reduce-only limit, marks the row `exit_order_type:
  "maker_resting"` (which `Ledger.due_trades/1` then skips) and answers `{:resting, trade}`;
  `exit_settled/2` books the close. A refused GTX crosses at once (`rejected_then_crossed`).
  The paper arms never come here — they are the scored rule and keep booking the bar price.

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
  alias FluxTrader.Trading.{ExchangeOrders, ExecCost, Ledger, LivePilot, PaperTrade, RiskManager}

  # The A/B's control arm is a measurement ledger and must never reach the exchange: it
  # exists to say what M2's raw gate would have earned, not to trade it.
  @paper_only_arms ["flat_size", "explore_cov05"]

  # The micro-pilot's arm goes to the exchange in EVERY mode but `auto`, and nowhere at all
  # unless `LivePilot.enabled?/0` — see that module. It is how real fills are taken while
  # the registered `policy` arm stays paper.
  @live_arm LivePilot.arm()

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
  A reduce/close order filled on the exchange — reported by `Binance.UserStream`. If
  `order_id` is the triggered order of an open row's stop or target algo, books the close
  on that row, cancels the sibling brake, and settles the risk manager. A fill no open row
  owns (our own timed close, whose row is already booked; a manual close) is ignored.
  """
  def brake_filled(symbol, order_id, avg_price)
      when is_binary(symbol) and is_integer(order_id) and is_number(avg_price),
      do: GenServer.call(__MODULE__, {:brake_filled, symbol, order_id, avg_price}, 30_000)

  @doc "A maker-path entry leg settled (its task reports here): rewrite the row from the leg, or drop it if nothing filled."
  def entry_settled(trade_id, result) when is_integer(trade_id),
    do: GenServer.call(__MODULE__, {:entry_settled, trade_id, result}, 30_000)

  @doc "A maker-path exit leg settled: book the close from the leg."
  def exit_settled(trade_id, result) when is_integer(trade_id),
    do: GenServer.call(__MODULE__, {:exit_settled, trade_id, result}, 30_000)

  @recover_after_ms 5_000

  @impl true
  def init(_opts) do
    config = Application.get_env(:fluxtrader, :trading, [])
    requested = Keyword.get(config, :mode, "simulation")
    {mode, refused} = resolve_mode(requested)

    Logger.info("Executor starting in #{mode} mode (the paper arms cross — M3-4; the pilot's maker path is M2)")

    if mode == "auto" do
      Logger.warning(
        "[AUTO] REAL ORDERS ARE LIVE against #{Client.trade_url()}" <>
          if(Client.testnet?(), do: " (TESTNET)", else: " (PRODUCTION)")
      )
    end

    if LivePilot.enabled?() do
      cfg = LivePilot.config()

      Logger.warning(
        "[LIVE] MICRO-PILOT IS ON: arm `live` places real orders against #{Client.trade_url()}" <>
          if(Client.testnet?(), do: " (TESTNET)", else: " (PRODUCTION)") <>
          " at $#{cfg[:notional_usd]} a trade, #{cfg[:leverage]}x, max #{cfg[:max_positions]} open" <>
          if(LivePilot.maker_path?(), do: " — MAKER PATH (M2): rest at the touch #{LivePilot.maker_wait_s()} s, then cross", else: "")
      )

      # A leg left resting by the last process is settled once the repo is up (M2).
      Process.send_after(self(), :recover_resting, @recover_after_ms)
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
       live_orders: state.mode == "auto" or LivePilot.enabled?(),
       trade_url: Client.trade_url(),
       testnet: Client.testnet?(),
       credentials_present: Client.credentials?(),
       filters_loaded: state.filters != nil,
       maker_path: LivePilot.maker_path?()
     }, state}
  end

  def handle_call({:entry_settled, trade_id, result}, _from, state) do
    {:reply, do_entry_settled(trade_id, result, state), state}
  end

  def handle_call({:exit_settled, trade_id, result}, _from, state) do
    {:reply, do_exit_settled(trade_id, result, state), state}
  end

  def handle_call({:open, arm, decision, order}, _from, state) do
    {reply, state} = do_open(state.mode, arm, decision, order, state)
    {:reply, reply, state}
  end

  def handle_call({:close, trade, exit_price}, _from, state) do
    {:reply, do_close(state.mode, trade, exit_price, state), state}
  end

  def handle_call({:brake_filled, symbol, order_id, avg_price}, _from, state) do
    {:reply, do_brake_filled(symbol, order_id, avg_price, state), state}
  end

  def handle_call(:get_positions, _from, state) do
    positions =
      Enum.flat_map(PaperTrade.all_arms(), fn arm ->
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

  @impl true
  def handle_info(:recover_resting, state) do
    {:noreply, recover_resting(state)}
  end

  @doc "Remember the last seen price for a pair, so open positions can be marked."
  def mark(pair, price) when is_number(price),
    do: GenServer.cast(__MODULE__, {:mark, pair, price})

  # ------------------------------------------------------------------ open

  defp do_open(_mode, @live_arm, decision, order, state) do
    cond do
      not LivePilot.enabled?() ->
        {{:error, :live_pilot_disabled}, state}

      foreign_position?(state.client, decision.pair) ->
        Logger.warning(
          "[LIVE] #{decision.pair}: the account already holds a position the pilot does not " <>
            "own (or it could not be read) — not mirrored"
        )

        {{:error, :foreign_position}, state}

      LivePilot.maker_path?() ->
        maker_open(decision, order, state)

      true ->
        exchange_open(@live_arm, decision, order, state)
    end
  end

  # The pilot shares a one-way account with its owner's manual trades (found 2026-09-21: three
  # manual positions on the day it was switched on). Its brakes are `closePosition` and its
  # close cancels every order on the symbol, so on a symbol that already carries a position
  # it would net against, stop out and cancel things it does not own. The engine never asks
  # for a pair with an open `live` row, so ANY non-zero position here is foreign. Fails
  # closed: an unreadable position is treated as a position.
  defp foreign_position?(client, symbol) do
    case client.position_risk(symbol) do
      {:ok, rows} when is_list(rows) -> Enum.any?(rows, &(position_amt(&1) != 0.0))
      _ -> true
    end
  end

  defp position_amt(%{"positionAmt" => amt}) when is_binary(amt) do
    case Float.parse(amt) do
      {f, _} -> f
      :error -> 1.0
    end
  end

  defp position_amt(%{"positionAmt" => amt}) when is_number(amt), do: amt * 1.0
  defp position_amt(_), do: 1.0

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

  defp do_open("auto", arm, decision, order, state),
    do: exchange_open(arm, decision, order, state)

  defp exchange_open(arm, decision, order, state) do
    with {:ok, filters, state} <- ensure_filters(state),
         req = order_req(decision, order),
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

  # ------------------------------------------------------------------ the maker path (M2)

  defp order_req(decision, order) do
    %{
      symbol: decision.pair,
      side: side_word(decision.side),
      quantity: order[:quantity],
      price: decision.entry_price,
      leverage: order[:leverage],
      stop_loss: order[:stop_loss],
      take_profit: order[:take_profit]
    }
  end

  defp maker_open(decision, order, state) do
    req = order_req(decision, order)

    with {:ok, filters, state} <- ensure_filters(state),
         {:ok, f, qty} <- ExchangeOrders.prepare_open(state.client, filters, req) do
      case ExchangeOrders.place_resting(state.client, f, req.symbol, req.side, qty, false) do
        {:resting, resting} ->
          overrides = %{
            entry_price: resting.rest_price,
            quantity: qty,
            notional: resting.rest_price * qty,
            cost_bps: ExecCost.fee_only_round_trip_bps(),
            fill_source: "exchange",
            entry_order_id: resting.order_id,
            entry_order_type: "maker_resting",
            entry_rest_price: resting.rest_price,
            entry_touch_bid: resting.touch.bid,
            entry_touch_ask: resting.touch.ask
          }

          case Ledger.open_trade(@live_arm, decision, overrides) do
            {:ok, trade} ->
              Logger.info(
                "[MAKER] RESTING #{req.side} #{req.symbol} #{qty} @ #{fmt(resting.rest_price)} " <>
                  "(touch #{fmt(resting.touch.bid)} / #{fmt(resting.touch.ask)}) order=#{resting.order_id} " <>
                  "for #{LivePilot.maker_wait_s()} s — row #{trade.id}"
              )

              settle_entry_async(state.client, trade.id, f, req, qty, resting)
              {{:ok, trade}, state}

            {:error, changeset} ->
              Logger.error(
                "[MAKER] rested #{req.symbol} but the ledger refused the row " <>
                  "(#{inspect(changeset.errors)}) — cancelling, unwinding whatever filled"
              )

              cancel_resting_or_unwind(state.client, f, req, qty, resting)
              {{:error, changeset}, state}
          end

        {:rejected, touch} ->
          case ExchangeOrders.cross_now(state.client, req.symbol, req.side, qty, touch, false) do
            {:ok, leg} ->
              fill = ExchangeOrders.fill_of_leg(leg)
              brakes = ExchangeOrders.place_brakes(state.client, f, req, fill)

              Logger.info(
                "[MAKER] GTX refused on #{req.symbol} (touch #{fmt(touch.bid)} / #{fmt(touch.ask)}) — " <>
                  "crossed: #{req.side} #{leg.executed_qty} @ #{fmt(leg.fill_price)} order=#{leg.order_id}"
              )

              overrides =
                Map.merge(entry_leg_overrides(leg, brakes), %{
                  cost_bps: leg.fee_bps + ExecCost.taker_fee_bps_per_side(),
                  fill_source: "exchange"
                })

              case Ledger.open_trade(@live_arm, decision, overrides) do
                {:ok, trade} ->
                  {{:ok, trade}, state}

                {:error, changeset} ->
                  Logger.error("[MAKER] crossed #{req.symbol} but the ledger refused the row (#{inspect(changeset.errors)}) — CLOSING")
                  unwind(state.client, req.symbol, side_word(-decision.side), Map.merge(fill, brakes))
                  {{:error, changeset}, state}
              end

            {:error, reason} ->
              Logger.error("[MAKER] crossing after a refused GTX failed for #{req.symbol}: #{inspect(reason)}")
              {{:error, reason}, state}
          end

        {:error, reason} ->
          Logger.error("[MAKER] resting order failed for #{req.symbol}: #{inspect(reason)}")
          {{:error, reason}, state}
      end
    else
      {:error, reason} ->
        Logger.error("[MAKER] order failed for #{decision.pair}: #{inspect(reason)}")
        {{:error, reason}, state}

      {:error, reason, state} ->
        Logger.error("[MAKER] order failed for #{decision.pair}: #{inspect(reason)}")
        {{:error, reason}, state}
    end
  end

  # The row's fields from a settled entry leg (the brakes are placed on the filled quantity).
  defp entry_leg_overrides(leg, brakes) do
    %{
      entry_price: leg.fill_price,
      entry_fill_price: leg.fill_price,
      quantity: leg.executed_qty,
      notional: leg.fill_price * leg.executed_qty,
      entry_order_id: leg.order_id,
      entry_order_type: leg.order_type,
      entry_rest_price: leg.rest_price,
      entry_wait_s: leg.wait_s,
      entry_fee_bps: leg.fee_bps,
      entry_touch_bid: leg.touch_bid,
      entry_touch_ask: leg.touch_ask,
      stop_order_id: brakes[:stop_order_id],
      target_order_id: brakes[:target_order_id]
    }
  end

  defp exit_leg_overrides(trade, leg, rest_at) do
    %{
      exit_reason: "timer",
      exit_order_id: leg.order_id,
      exit_order_type: leg.order_type,
      exit_rest_price: leg.rest_price,
      exit_wait_s: leg.wait_s,
      exit_fill_price: leg.fill_price,
      exit_fee_bps: leg.fee_bps,
      exit_touch_bid: leg.touch_bid,
      exit_touch_ask: leg.touch_ask,
      exit_rest_at: rest_at,
      cost_bps: (trade.entry_fee_bps || ExecCost.taker_fee_bps_per_side()) + leg.fee_bps
    }
  end

  defp settle_entry_async(client, trade_id, f, req, qty, resting) do
    wait_s = LivePilot.maker_wait_s()

    Task.Supervisor.start_child(FluxTrader.TaskSupervisor, fn ->
      result =
        case ExchangeOrders.settle_resting(client, f, req.symbol, req.side, qty, resting, wait_s, false) do
          {:ok, leg} ->
            fill = ExchangeOrders.fill_of_leg(leg)
            {:ok, leg, ExchangeOrders.place_brakes(client, f, req, fill)}

          {:error, reason} ->
            {:error, reason}
        end

      __MODULE__.entry_settled(trade_id, result)
    end)
  end

  defp settle_exit_async(client, trade_id, f, symbol, side, qty, resting) do
    wait_s = LivePilot.maker_wait_s()

    Task.Supervisor.start_child(FluxTrader.TaskSupervisor, fn ->
      result = ExchangeOrders.settle_resting(client, f, symbol, side, qty, resting, wait_s, true)
      __MODULE__.exit_settled(trade_id, result)
    end)
  end

  defp do_entry_settled(trade_id, result, _state) do
    case Ledger.reload(%PaperTrade{id: trade_id}) do
      %PaperTrade{status: "open", entry_order_type: "maker_resting"} = trade ->
        case result do
          {:ok, leg, brakes} ->
            overrides =
              Map.put(entry_leg_overrides(leg, brakes), :cost_bps, leg.fee_bps + ExecCost.taker_fee_bps_per_side())

            case Ledger.update_trade(trade, overrides) do
              {:ok, updated} ->
                Logger.info(
                  "[MAKER] ENTRY #{updated.pair} #{leg.order_type}: #{leg.executed_qty} @ #{fmt(leg.fill_price)} " <>
                    "(rest #{fmt(leg.rest_price)}, waited #{Float.round(leg.wait_s, 1)} s, fee #{fmt(leg.fee_bps)} bps) " <>
                    "stop=#{inspect(brakes[:stop_order_id])} target=#{inspect(brakes[:target_order_id])} — row #{updated.id}"
                )

                {:ok, updated}

              {:error, changeset} ->
                Logger.error("[MAKER] row #{trade.id} could not take its settled entry (#{inspect(changeset.errors)}) — it stays as placed; MANUAL CHECK")
                {:error, changeset}
            end

          {:error, reason} ->
            # Nothing filled at the rest and the crossing order failed: there is no position,
            # so there must be no row.
            Logger.error("[MAKER] entry on #{trade.pair} filled nothing and could not cross (#{inspect(reason)}) — dropping row #{trade.id}")
            Ledger.delete_trade(trade)
            {:error, reason}
        end

      other ->
        Logger.warning("[MAKER] entry_settled for row #{trade_id} found #{inspect(other && other.status)} / #{inspect(other && other.entry_order_type)} — ignored")
        {:error, :not_resting}
    end
  end

  defp do_exit_settled(trade_id, result, state) do
    case Ledger.reload(%PaperTrade{id: trade_id}) do
      %PaperTrade{status: "open", exit_order_type: "maker_resting"} = trade ->
        case result do
          {:ok, leg} ->
            finish_close(trade, leg.fill_price, exit_leg_overrides(trade, leg, trade.exit_rest_at))

          {:error, {_status, %{"code" => -2022}}} ->
            # The position was gone before the remainder could cross: a brake fired during
            # the rest, or it was closed by hand.
            brake_or_missing(trade, state)

          {:error, reason} ->
            # The leg could not be settled; the position may well still be there. Free the
            # row so the next tick tries the close again rather than leaving it stuck.
            Logger.error("[MAKER] exit on #{trade.pair} could not settle (#{inspect(reason)}) — the row goes back to due; MANUAL CHECK if it repeats")
            Ledger.update_trade(trade, %{exit_order_type: nil, exit_order_id: nil})
            {:error, reason}
        end

      other ->
        Logger.warning("[MAKER] exit_settled for row #{trade_id} found #{inspect(other && other.status)} / #{inspect(other && other.exit_order_type)} — ignored")
        {:error, :not_resting}
    end
  end

  defp finish_close(trade, price, overrides) do
    case book_close("MAKER", trade, price, overrides) do
      {:ok, closed} ->
        RiskManager.record_closed_trade(closed)
        {:ok, closed}

      other ->
        other
    end
  end

  defp brake_or_missing(trade, state) do
    req = %{symbol: trade.pair, stop_order_id: trade.stop_order_id, target_order_id: trade.target_order_id}

    case ExchangeOrders.brake_exit(state.client, req) do
      {:ok, fill} ->
        finish_close(trade, fill.avg_price, %{exit_reason: fill.exit_reason, exit_order_id: fill.order_id, exit_order_type: nil})

      {:error, :position_missing} ->
        mark = Map.get(state.marks, trade.pair) || trade.exit_rest_price || trade.entry_price
        Logger.error("[MAKER] #{trade.pair}: no position on the exchange and no brake filled — booking at the mark #{fmt(mark)} as position_missing")
        finish_close(trade, mark, %{exit_reason: "position_missing", exit_order_type: nil})
    end
  end

  # The ledger refused the row of a resting entry: cancel it; if it filled in the meantime,
  # close that position — a position without a row is the one state never left behind.
  defp cancel_resting_or_unwind(client, f, req, qty, resting) do
    case ExchangeOrders.settle_resting(client, f, req.symbol, req.side, qty, %{resting | placed_at_ms: 0}, 0, false) do
      {:ok, leg} when leg.executed_qty > 0.0 ->
        unwind(client, req.symbol, if(req.side == "BUY", do: "SELL", else: "BUY"), %{
          executed_qty: leg.executed_qty,
          stop_order_id: nil,
          target_order_id: nil
        })

      _ ->
        :ok
    end
  end

  # After a restart: every open live row with a leg still marked resting is settled now —
  # the rest is treated as over (its W has almost surely elapsed; if not, a few seconds of
  # it are forgone), so the leg is cancelled and crossed on the same path as a timed-out
  # rest. The wait recorded is the real elapsed time.
  defp recover_resting(state) do
    rows = Ledger.resting_legs()

    if rows == [] do
      state
    else
      case ensure_filters(state) do
        {:ok, filters, state} ->
          Enum.each(rows, &recover_row(&1, filters, state))
          state

        {:error, reason, state} ->
          Logger.error("[MAKER] #{length(rows)} resting leg(s) found after restart but the filters could not be loaded (#{inspect(reason)}) — retrying in #{@recover_after_ms} ms")
          Process.send_after(self(), :recover_resting, @recover_after_ms)
          state
      end
    end
  rescue
    e ->
      Logger.error("[MAKER] recover_resting failed: #{Exception.message(e)}")
      state
  end

  defp recover_row(%PaperTrade{} = t, filters, state) do
    with {:ok, f} <- ExchangeOrders.symbol_filters(filters, t.pair) do
      now_ms = System.monotonic_time(:millisecond)

      cond do
        t.entry_order_type == "maker_resting" ->
          elapsed = DateTime.diff(DateTime.utc_now(), t.inserted_at, :millisecond)
          resting = %{order_id: t.entry_order_id, rest_price: t.entry_rest_price, placed_at_ms: now_ms - elapsed,
                      touch: %{bid: t.entry_touch_bid, ask: t.entry_touch_ask}, status: "NEW"}
          req = %{symbol: t.pair, side: side_word(t.side), stop_loss: nil, take_profit: nil}
          Logger.warning("[MAKER] restart: settling the resting ENTRY of row #{t.id} (#{t.pair}, placed #{div(elapsed, 1000)} s ago)")
          settle_entry_async(state.client, t.id, f, req, t.quantity, resting)

        t.exit_order_type == "maker_resting" ->
          elapsed = DateTime.diff(DateTime.utc_now(), t.exit_rest_at || t.updated_at, :millisecond)
          resting = %{order_id: t.exit_order_id, rest_price: t.exit_rest_price, placed_at_ms: now_ms - elapsed,
                      touch: %{bid: t.exit_touch_bid, ask: t.exit_touch_ask}, status: "NEW"}
          Logger.warning("[MAKER] restart: settling the resting EXIT of row #{t.id} (#{t.pair}, placed #{div(elapsed, 1000)} s ago)")
          settle_exit_async(state.client, t.id, f, t.pair, side_word(-t.side), t.quantity, resting)

        true ->
          :ok
      end
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

  # An exchange-filled row closes on the exchange whatever the mode is now: the position is
  # real, and the micro-pilot's `live` rows exist while the mode is `simulation`.
  defp do_close(_mode, %PaperTrade{fill_source: "exchange"} = trade, mark_price, state) do
    # Re-read first: a brake may have filled and been booked by the user-data stream
    # between the due-list read and now, and a closed row must not be booked twice.
    case Ledger.reload(trade) do
      %PaperTrade{status: "open", arm: @live_arm, entry_order_type: t} = trade
      when t != nil and t != "maker_resting" ->
        # An entry the maker path placed exits on the maker path (M2) — whatever the flag
        # says now, so a row is measured whole or not at all. A still-resting entry is
        # never due: its task settles it first.
        maker_close(trade, mark_price, state)

      %PaperTrade{status: "open", entry_order_type: "maker_resting"} ->
        {:error, :entry_resting}

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

  defp maker_close(trade, mark_price, state) do
    side = side_word(-trade.side)
    now = DateTime.utc_now() |> DateTime.truncate(:second)

    with {:ok, filters, _state} <- ensure_filters(state),
         {:ok, f} <- ExchangeOrders.symbol_filters(filters, trade.pair) do
      ExchangeOrders.cancel_brakes(state.client, trade.pair)

      case ExchangeOrders.place_resting(state.client, f, trade.pair, side, trade.quantity, true) do
        {:resting, resting} ->
          case Ledger.update_trade(trade, %{
                 exit_order_type: "maker_resting",
                 exit_order_id: resting.order_id,
                 exit_rest_price: resting.rest_price,
                 exit_touch_bid: resting.touch.bid,
                 exit_touch_ask: resting.touch.ask,
                 exit_rest_at: now
               }) do
            {:ok, updated} ->
              Logger.info(
                "[MAKER] EXIT RESTING #{side} #{trade.pair} #{trade.quantity} @ #{fmt(resting.rest_price)} " <>
                  "(touch #{fmt(resting.touch.bid)} / #{fmt(resting.touch.ask)}) order=#{resting.order_id} — row #{trade.id}"
              )

              settle_exit_async(state.client, trade.id, f, trade.pair, side, trade.quantity, resting)
              {:resting, updated}

            {:error, changeset} ->
              Logger.error("[MAKER] exit rested on #{trade.pair} but the row refused the update (#{inspect(changeset.errors)}) — settling it now")
              result = ExchangeOrders.settle_resting(state.client, f, trade.pair, side, trade.quantity, resting, 0, true)

              case result do
                {:ok, leg} -> finish_close(trade, leg.fill_price, exit_leg_overrides(trade, leg, now))
                {:error, {_s, %{"code" => -2022}}} -> brake_or_missing(trade, state)
                {:error, reason} -> {:error, reason}
              end
          end

        {:rejected, touch} ->
          case ExchangeOrders.cross_now(state.client, trade.pair, side, trade.quantity, touch, true) do
            {:ok, leg} ->
              Logger.info("[MAKER] GTX refused on the exit of #{trade.pair} — crossed @ #{fmt(leg.fill_price)}")
              finish_close(trade, leg.fill_price, exit_leg_overrides(trade, leg, now))

            {:error, {_s, %{"code" => -2022}}} ->
              brake_or_missing(trade, state)

            {:error, reason} ->
              Logger.error("[MAKER] crossing the exit of #{trade.pair} failed: #{inspect(reason)}")
              {:error, reason}
          end

        {:error, {_s, %{"code" => -2022}}} ->
          brake_or_missing(trade, state)

        {:error, reason} ->
          Logger.error("[MAKER] exit rest on #{trade.pair} failed: #{inspect(reason)} (mark #{fmt(mark_price)})")
          {:error, reason}
      end
    else
      {:error, reason} -> {:error, reason}
      {:error, reason, _state} -> {:error, reason}
    end
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

  defp do_brake_filled(symbol, order_id, avg_price, state) do
    match =
      Enum.find_value(Ledger.open_exchange_trades(symbol), fn trade ->
        case ExchangeOrders.which_brake(state.client, symbol, order_id,
               [trade.stop_order_id, trade.target_order_id]) do
          {:ok, 0} -> {trade, "stop"}
          {:ok, 1} -> {trade, "target"}
          :none -> nil
        end
      end)

    case match do
      nil ->
        Logger.info("[AUTO] fill on #{symbol} order #{order_id} is not an open row's brake — ignored")
        {:error, :unknown_order}

      {%PaperTrade{} = trade, reason} ->
        Logger.warning(
          "[AUTO] BRAKE FIRED: #{reason} on #{trade.pair} @ #{fmt(avg_price)} (order #{order_id})"
        )

        # The sibling brake is still resting and would act on the NEXT position on this
        # symbol if it were left there.
        ExchangeOrders.cancel_brakes(state.client, trade.pair)

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
