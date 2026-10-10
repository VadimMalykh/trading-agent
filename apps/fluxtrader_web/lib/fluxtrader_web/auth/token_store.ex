defmodule FluxTraderWeb.Auth.TokenStore do
  @moduledoc """
  The two bits of state magic links need: spent token nonces (so a link signs in once) and the
  last send per email (so the login form cannot flood an inbox). In memory: a restart forgets
  both, which at worst lets a still-valid (≤15 min) link be used once more.
  """
  use Agent

  @throttle_s 60

  def start_link(_), do: Agent.start_link(fn -> %{used: %{}, sent: %{}} end, name: __MODULE__)

  @doc "`:ok` the first time a nonce is seen within `ttl_s`, `{:error, :used}` after."
  def consume(nonce, ttl_s) do
    now = now()

    Agent.get_and_update(__MODULE__, fn %{used: used} = s ->
      used = Map.reject(used, fn {_, exp} -> exp <= now end)

      if Map.has_key?(used, nonce),
        do: {{:error, :used}, %{s | used: used}},
        else: {:ok, %{s | used: Map.put(used, nonce, now + ttl_s)}}
    end)
  end

  @doc "`:ok` at most once per #{@throttle_s} s per email."
  def throttle(email) do
    now = now()

    Agent.get_and_update(__MODULE__, fn %{sent: sent} = s ->
      case sent do
        %{^email => at} when now - at < @throttle_s -> {{:error, :throttled}, s}
        _ -> {:ok, %{s | sent: Map.put(sent, email, now)}}
      end
    end)
  end

  @doc false
  def reset, do: Agent.update(__MODULE__, fn _ -> %{used: %{}, sent: %{}} end)

  defp now, do: System.system_time(:second)
end
