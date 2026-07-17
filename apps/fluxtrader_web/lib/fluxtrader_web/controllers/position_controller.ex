defmodule FluxTraderWeb.PositionController do
  use FluxTraderWeb, :controller

  def index(conn, _params) do
    positions = FluxTrader.Trading.Executor.get_positions()
    json(conn, %{positions: positions})
  end
end
