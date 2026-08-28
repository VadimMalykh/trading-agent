defmodule FluxTrader.Application do
  @moduledoc """
  Core application supervisor.

  The tree splits in two. **Infrastructure** — PubSub, the HTTP pool, the repo, the task
  supervisor — always starts. **Runtime workers** — anything that opens a socket to Binance,
  polls inference, or decides to trade — start only outside the test environment, and tests
  start the one or two they need under their own supervision. Without that split, `mix test`
  would open a live market-data websocket and run the policy loop against the exchange.
  """
  use Application

  @impl true
  def start(_type, _args) do
    children = infrastructure() ++ workers()
    Supervisor.start_link(children, strategy: :one_for_one, name: FluxTrader.Supervisor)
  end

  defp infrastructure do
    [
      {Phoenix.PubSub, name: FluxTrader.PubSub},
      {Finch, name: FluxTrader.Finch},
      FluxTrader.Repo,
      {Task.Supervisor, name: FluxTrader.TaskSupervisor}
    ]
  end

  defp workers do
    if Application.get_env(:fluxtrader, :start_workers, true) do
      [
        FluxTrader.Binance.WebSocket,
        FluxTrader.Data.CandleStore,
        FluxTrader.Pairs.Selector,
        FluxTrader.MarketData.Collector,
        FluxTrader.Trading.Executor,
        FluxTrader.Trading.RiskManager,
        FluxTrader.Trading.Regime,
        FluxTrader.Notifications.Telegram.RateLimiter,
        FluxTrader.ML.SignalEngine,
        # Last: it subscribes to the signal engine's broadcasts and reads the regime.
        FluxTrader.Trading.PolicyEngine
      ]
    else
      []
    end
  end
end
