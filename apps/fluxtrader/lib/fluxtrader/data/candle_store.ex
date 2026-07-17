defmodule FluxTrader.Data.CandleStore do
  @moduledoc """
  In-memory candle store. Buffers incoming candle data and broadcasts updates.
  """
  use GenServer
  require Logger

  def start_link(opts) do
    GenServer.start_link(__MODULE__, opts, name: __MODULE__)
  end

  def handle_message(%{symbol: _symbol, interval: _interval, close: _close} = candle) do
    GenServer.cast(__MODULE__, {:handle_candle, candle})
  end

  def handle_message(_other), do: :ok

  def get_candles(symbol, interval, limit \\ 100) do
    GenServer.call(__MODULE__, {:get_candles, symbol, interval, limit})
  end

  @impl true
  def init(_opts) do
    {:ok, %{candles: %{}}}
  end

  @impl true
  def handle_cast({:handle_candle, candle}, state) do
    key = {candle.symbol, candle.interval}
    candles = Map.update(state.candles, key, [candle], fn existing -> [candle | existing] end)
    {:noreply, %{state | candles: candles}}
  end

  @impl true
  def handle_call({:get_candles, symbol, interval, limit}, _from, state) do
    key = {symbol, interval}
    candles = state.candles |> Map.get(key, []) |> Enum.take(limit)
    {:reply, candles, state}
  end
end
