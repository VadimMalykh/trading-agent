defmodule FluxTraderWeb.Application do
  @moduledoc false
  use Application

  @impl true
  def start(_type, _args) do
    children = [
      FluxTraderWeb.Telemetry,
      {Phoenix.PubSub, name: FluxTraderWeb.PubSub},
      FluxTraderWeb.Endpoint
    ]

    opts = [strategy: :one_for_one, name: FluxTraderWeb.Supervisor]
    Supervisor.start_link(children, opts)
  end

  @impl true
  def config_change(changed, _new, removed) do
    FluxTraderWeb.Endpoint.config_change(changed, removed)
    :ok
  end
end
