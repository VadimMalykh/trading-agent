defmodule FluxTrader.Application do
  @moduledoc """
  Core application supervisor.
  """
  use Application

  @impl true
  def start(_type, _args) do
    children = [
      {Phoenix.PubSub, name: FluxTrader.PubSub},
      {Finch, name: FluxTrader.Finch},
      FluxTrader.Repo,
      {Task.Supervisor, name: FluxTrader.TaskSupervisor},
      FluxTrader.Binance.WebSocket,
      FluxTrader.MarketData.Collector,
      FluxTrader.Data.CandleStore,
      FluxTrader.Pairs.Selector,
      FluxTrader.Trading.Executor,
      FluxTrader.Trading.RiskManager
    ]

    opts = [strategy: :one_for_one, name: FluxTrader.Supervisor]
    Supervisor.start_link(children, opts)
  end
end
