defmodule FluxTrader.Binance.Auth do
  @moduledoc """
  Request signing for Binance's SIGNED endpoints (TRADE, USER_DATA).

  Binance signs the **payload** — the query string for GET/DELETE, the form body for POST —
  with HMAC-SHA256 under the API secret, hex-encoded lowercase, and expects it appended as
  `signature=`. The payload must carry a `timestamp` (ms) and may carry `recvWindow`. The
  API key travels separately in the `X-MBX-APIKEY` header and is never part of the signature.

  This is the one place the arithmetic lives. `mix flux.fee_tier` used to carry its own copy;
  `Binance.Trade.Rest` and the fee-tier task both call here now, so a signing bug is one bug.
  """

  @recv_window 5_000

  @doc "Hex HMAC-SHA256 of `payload` under `secret`, exactly as Binance expects it."
  def sign(secret, payload) when is_binary(secret) and is_binary(payload) do
    :crypto.mac(:hmac, :sha256, secret, payload) |> Base.encode16(case: :lower)
  end

  @doc """
  Encode `params`, stamp `timestamp` and `recvWindow`, and append the signature.

  Returns the complete payload string, ready to be a query string or a form body. `nil`
  values are dropped so callers can pass optional parameters without filtering them first.
  `now_ms` is injectable for tests.
  """
  def signed_payload(params, secret, now_ms \\ System.system_time(:millisecond)) do
    base =
      params
      |> Enum.reject(fn {_k, v} -> is_nil(v) end)
      |> Enum.map(fn {k, v} -> {to_atom(k), to_param(v)} end)
      |> Keyword.delete(:timestamp)

    # Appended, not prepended: order is irrelevant to the exchange as long as the signed
    # string is the sent string, but keeping the caller's parameters first makes a logged
    # payload readable.
    base =
      if Keyword.has_key?(base, :recvWindow), do: base, else: base ++ [recvWindow: @recv_window]

    query = URI.encode_query(base ++ [timestamp: now_ms])

    query <> "&signature=" <> sign(secret, query)
  end

  defp to_atom(k) when is_atom(k), do: k
  defp to_atom(k) when is_binary(k), do: String.to_atom(k)

  # Binance parses "true"/"false" strings for boolean parameters, and floats must not be
  # rendered in scientific notation — `:erlang.float_to_binary/2` with `:short` keeps them
  # plain and minimal.
  defp to_param(true), do: "true"
  defp to_param(false), do: "false"
  defp to_param(f) when is_float(f), do: :erlang.float_to_binary(f, [:short])
  defp to_param(v), do: v
end
