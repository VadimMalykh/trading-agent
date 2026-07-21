defmodule FluxTraderWeb.SignalController do
  use FluxTraderWeb, :controller

  def index(conn, _params) do
    latest = FluxTrader.ML.SignalEngine.latest()

    json(conn, %{
      inference_ok: latest.inference_ok,
      last_error: latest.last_error,
      last_run_at: latest.last_run_at,
      signals: latest.signals |> Map.values()
    })
  end
end
