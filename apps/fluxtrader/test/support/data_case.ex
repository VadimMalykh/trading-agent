defmodule FluxTrader.DataCase do
  @moduledoc """
  Test case for anything that touches the repo. Each test runs inside a transaction that is
  rolled back, so the paper ledger a test writes never leaks into the next one.
  """
  use ExUnit.CaseTemplate

  using do
    quote do
      alias FluxTrader.Repo
      import Ecto.Query
      import FluxTrader.DataCase
    end
  end

  setup tags do
    pid = Ecto.Adapters.SQL.Sandbox.start_owner!(FluxTrader.Repo, shared: not tags[:async])
    on_exit(fn -> Ecto.Adapters.SQL.Sandbox.stop_owner(pid) end)
    :ok
  end
end
