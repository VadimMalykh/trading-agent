defmodule FluxTrader.Notifications.Telegram.RateLimiter do
  @moduledoc """
  Tracks the last time a trade signal was sent to Telegram per symbol+horizon,
  so signals are not re-sent more often than their horizon length.
  """

  use Agent

  def start_link(_opts) do
    Agent.start_link(fn -> %{} end, name: __MODULE__)
  end
end
