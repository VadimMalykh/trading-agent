defmodule FluxTrader.Pairs.Selector do
  @moduledoc """
  Manages the whitelist of trading pairs and pair scoring.
  """
  use GenServer

  def start_link(opts) do
    GenServer.start_link(__MODULE__, opts, name: __MODULE__)
  end

  def active_pairs do
    GenServer.call(__MODULE__, :active_pairs)
  end

  def update_whitelist(pairs) do
    GenServer.cast(__MODULE__, {:update_whitelist, pairs})
  end

  @impl true
  def init(_opts) do
    config = Application.get_env(:fluxtrader, :trading, [])
    pairs = Keyword.get(config, :whitelist_pairs, ["BTCUSDT", "ETHUSDT", "SOLUSDT"])

    {:ok, %{pairs: pairs}}
  end

  @impl true
  def handle_call(:active_pairs, _from, state) do
    {:reply, state.pairs, state}
  end

  @impl true
  def handle_cast({:update_whitelist, pairs}, state) do
    {:noreply, %{state | pairs: pairs}}
  end
end
