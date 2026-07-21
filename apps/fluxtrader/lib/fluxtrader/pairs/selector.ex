defmodule FluxTrader.Pairs.Selector do
  @moduledoc """
  Whitelist of trading pairs. Persisted via FluxTrader.Settings (Postgres).
  """
  use GenServer
  require Logger

  def start_link(opts) do
    GenServer.start_link(__MODULE__, opts, name: __MODULE__)
  end

  def active_pairs do
    GenServer.call(__MODULE__, :active_pairs)
  end

  def update_whitelist(pairs) when is_list(pairs) do
    GenServer.call(__MODULE__, {:update_whitelist, pairs})
  end

  def add_pair(pair) when is_binary(pair) do
    GenServer.call(__MODULE__, {:add_pair, pair})
  end

  def remove_pair(pair) when is_binary(pair) do
    GenServer.call(__MODULE__, {:remove_pair, pair})
  end

  @impl true
  def init(_opts) do
    pairs = safe_load_pairs()
    Logger.info("Pairs.Selector loaded whitelist: #{inspect(pairs)}")
    # Notify subscribers after they have a chance to start/subscribe
    {:ok, %{pairs: pairs}, {:continue, :broadcast}}
  end

  @impl true
  def handle_continue(:broadcast, state) do
    broadcast(state.pairs)
    {:noreply, state}
  end

  @impl true
  def handle_call(:active_pairs, _from, state) do
    {:reply, state.pairs, state}
  end

  def handle_call({:update_whitelist, pairs}, _from, state) do
    pairs = FluxTrader.Settings.put_whitelist(pairs)
    broadcast(pairs)
    {:reply, {:ok, pairs}, %{state | pairs: pairs}}
  end

  def handle_call({:add_pair, pair}, _from, state) do
    pair = String.upcase(String.trim(pair))

    pairs =
      if pair != "" and pair not in state.pairs do
        FluxTrader.Settings.put_whitelist(state.pairs ++ [pair])
      else
        state.pairs
      end

    broadcast(pairs)
    {:reply, {:ok, pairs}, %{state | pairs: pairs}}
  end

  def handle_call({:remove_pair, pair}, _from, state) do
    pairs =
      state.pairs
      |> Enum.reject(&(&1 == pair))
      |> FluxTrader.Settings.put_whitelist()

    broadcast(pairs)
    {:reply, {:ok, pairs}, %{state | pairs: pairs}}
  end

  defp safe_load_pairs do
    try do
      FluxTrader.Settings.get_whitelist()
    rescue
      e ->
        Logger.warning("Settings load failed: #{inspect(e)}; using config defaults")
        Application.get_env(:fluxtrader, :trading, [])
        |> Keyword.get(:whitelist_pairs, ["BTCUSDT", "ETHUSDT", "SOLUSDT"])
    end
  end

  defp broadcast(pairs) do
    Phoenix.PubSub.broadcast(FluxTrader.PubSub, "settings:whitelist", {:whitelist, pairs})
  end
end
