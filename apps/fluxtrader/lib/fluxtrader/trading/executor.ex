defmodule FluxTrader.Trading.Executor do
  @moduledoc """
  Executes trade orders on Binance Futures.
  Handles order placement, modification, and cancellation.
  """
  use GenServer
  require Logger

  def start_link(opts) do
    GenServer.start_link(__MODULE__, opts, name: __MODULE__)
  end

  def execute(signal) do
    GenServer.call(__MODULE__, {:execute, signal})
  end

  def get_positions do
    GenServer.call(__MODULE__, :get_positions)
  end

  @impl true
  def init(_opts) do
    config = Application.get_env(:fluxtrader, :trading, [])

    state = %{
      mode: Keyword.get(config, :mode, "simulation"),
      positions: [],
      leverage: Keyword.get(config, :leverage, 5)
    }

    {:ok, state}
  end

  @impl true
  def handle_call({:execute, signal}, _from, state) do
    case state.mode do
      "simulation" ->
        Logger.info("[SIM] Signal: #{signal.side} #{signal.symbol} @ #{signal.confidence}")
        position = build_mock_position(signal)
        {:reply, {:ok, position}, %{state | positions: [position | state.positions]}}

      "signal" ->
        Logger.info("[SIGNAL] #{signal.side} #{signal.symbol} conf=#{signal.confidence}")
        {:reply, {:ok, :signal_only}, state}

      "manual" ->
        Logger.info("[MANUAL] Pending approval: #{signal.side} #{signal.symbol}")
        {:reply, {:ok, :pending_approval}, state}

      "auto" ->
        place_order(signal, state)
    end
  end

  def handle_call(:get_positions, _from, state) do
    {:reply, state.positions, state}
  end

  defp place_order(signal, state) do
    case FluxTrader.Binance.Client.place_order(signal) do
      {:ok, order} ->
        position = %{order | status: :open}
        {:reply, {:ok, position}, %{state | positions: [position | state.positions]}}

      {:error, reason} ->
        Logger.error("Order failed: #{inspect(reason)}")
        {:reply, {:error, reason}, state}
    end
  end

  defp build_mock_position(signal) do
    %{
      id: System.unique_integer([:positive]),
      symbol: signal.symbol,
      side: signal.side,
      entry_price: signal.price,
      quantity: signal.quantity,
      leverage: signal.leverage || 5,
      stop_loss: signal.stop_loss,
      take_profit: signal.take_profit,
      status: :open,
      opened_at: DateTime.utc_now(),
      pnl: 0.0
    }
  end
end
