defmodule FluxTrader.Binance.WebSocket do
  @moduledoc """
  Placeholder GenServer for Binance data feed.

  Candle polling and broadcasting is handled by MarketData.Collector.
  This module is kept in the supervision tree for future actual WebSocket use.
  """
  use GenServer
  require Logger

  def start_link(opts) do
    GenServer.start_link(__MODULE__, opts, name: __MODULE__)
  end

  @impl true
  def init(_opts) do
    Logger.info("Binance.WebSocket started (polling handled by MarketData.Collector)")
    {:ok, %{}}
  end
end
