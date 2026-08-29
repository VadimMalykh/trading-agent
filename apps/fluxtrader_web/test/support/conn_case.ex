defmodule FluxTraderWeb.ConnCase do
  @moduledoc """
  Test case for anything that renders. It owns a sandboxed repo connection in shared mode,
  because a connected LiveView runs in its own process and would otherwise be unable to read
  the bar log and the paper ledger the M3 panel is built from.
  """
  use ExUnit.CaseTemplate

  using do
    quote do
      @endpoint FluxTraderWeb.Endpoint

      use FluxTraderWeb, :verified_routes

      import Plug.Conn
      import Phoenix.ConnTest
    end
  end

  setup tags do
    pid = Ecto.Adapters.SQL.Sandbox.start_owner!(FluxTrader.Repo, shared: not tags[:async])
    on_exit(fn -> Ecto.Adapters.SQL.Sandbox.stop_owner(pid) end)
    {:ok, conn: Phoenix.ConnTest.build_conn()}
  end
end
