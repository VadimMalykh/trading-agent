defmodule FluxTraderWeb.Auth do
  @moduledoc """
  Magic-link sign-in for a whitelisted set of emails — on the VM only.

  **On iff `AUTH_ALLOWED_EMAILS` is non-empty.** Local compose leaves it unset and the app
  stays open, as it always was. On `fluxtrader-1` port 4000 is open to the internet, and the
  Settings page can switch the trading mode, so there it must be set.

  The flow: `/login` takes an email; a whitelisted one is mailed a link carrying a signed
  token (15 min, single use); the link's page POSTs it back (a GET never signs in, so a mail
  scanner prefetching the link cannot spend it); the session then holds the email for 30 days
  and every request re-checks it against the current whitelist.

  `/api/*` stays reachable without a session from private and loopback addresses, so
  `curl localhost:4000/api/health` on the VM keeps working (Docker's port proxy presents a
  host-local curl as the bridge gateway, 172.x; outside traffic keeps its public source).
  🔴 Put a reverse proxy in front and every request becomes private — then this shortcut has
  to go or read a trusted forwarded header.

  🔴 Fails closed: enabled with the repo's public dev `SECRET_KEY_BASE` (anyone could forge a
  session cookie with it) means nobody gets in, not everybody. It does not crash at boot — the
  same app runs the collector.
  """

  import Plug.Conn
  import Phoenix.Controller, only: [redirect: 2, json: 2]

  require Logger

  alias FluxTraderWeb.Auth.TokenStore

  @token_salt "magic-link"
  @token_max_age 15 * 60
  @session_max_age 30 * 24 * 3600
  @dev_secret_prefixes ["dev-only-", "test-only-"]

  def token_max_age, do: @token_max_age
  def session_max_age, do: @session_max_age

  defp config, do: Application.get_env(:fluxtrader_web, :auth, [])

  def allowed_emails, do: Keyword.get(config(), :allowed_emails, [])

  @doc "`:disabled`, `:enabled`, or `{:misconfigured, reason}` (enabled, but nobody may sign in)."
  def status do
    cond do
      allowed_emails() == [] ->
        :disabled

      Keyword.get(config(), :allow_dev_secret, false) ->
        :enabled

      weak_secret?(FluxTraderWeb.Endpoint.config(:secret_key_base)) ->
        {:misconfigured, "SECRET_KEY_BASE is unset or the public dev default"}

      true ->
        :enabled
    end
  end

  def enabled?, do: status() != :disabled

  defp weak_secret?(s) when is_binary(s),
    do: byte_size(s) < 64 or Enum.any?(@dev_secret_prefixes, &String.starts_with?(s, &1))

  defp weak_secret?(_), do: true

  def normalize(email) when is_binary(email), do: email |> String.trim() |> String.downcase()
  def normalize(_), do: ""

  def allowed?(email), do: status() == :enabled and normalize(email) in allowed_emails()

  # -- the link -------------------------------------------------------------------------------

  @doc "Mail a sign-in link to `email` if it is whitelisted. Always `:ok` — no enumeration."
  def request_link(email) do
    email = normalize(email)

    with true <- allowed?(email),
         :ok <- TokenStore.throttle(email) do
      nonce = Base.url_encode64(:crypto.strong_rand_bytes(16), padding: false)
      token = Phoenix.Token.sign(FluxTraderWeb.Endpoint, @token_salt, %{"e" => email, "n" => nonce})
      FluxTraderWeb.Auth.Mailer.deliver_link(email, base_url() <> "/login/" <> token)
    else
      false -> Logger.info("auth: sign-in link refused for a non-whitelisted address")
      {:error, :throttled} -> Logger.info("auth: sign-in link throttled")
    end

    :ok
  end

  @doc "Spend a token: `{:ok, email}` once, then `{:error, :used}`."
  def consume(token) do
    with {:ok, %{"e" => email, "n" => nonce}} <-
           Phoenix.Token.verify(FluxTraderWeb.Endpoint, @token_salt, token,
             max_age: @token_max_age
           ),
         true <- allowed?(email) || {:error, :not_allowed},
         :ok <- TokenStore.consume(nonce, @token_max_age) do
      {:ok, email}
    else
      {:error, reason} -> {:error, reason}
      _ -> {:error, :invalid}
    end
  end

  # The link is built from config, never from the request's Host header: a forged Host would
  # otherwise mail Vadim a real token pointing at someone else's server.
  defp base_url do
    (Keyword.get(config(), :base_url) || FluxTraderWeb.Endpoint.url())
    |> String.trim_trailing("/")
  end

  # -- session --------------------------------------------------------------------------------

  def log_in(conn, email) do
    conn
    |> configure_session(renew: true)
    |> put_session(:auth_email, email)
    |> put_session(:auth_at, System.system_time(:second))
  end

  def log_out(conn), do: configure_session(conn, drop: true)

  @doc "The signed-in email for a session map, or nil."
  def session_email(session) do
    email = session["auth_email"]
    at = session["auth_at"]

    if is_integer(at) and System.system_time(:second) - at < @session_max_age and allowed?(email),
      do: email
  end

  # -- plugs and LiveView hook ----------------------------------------------------------------

  def init(action), do: action

  def call(conn, :browser) do
    cond do
      not enabled?() ->
        conn

      email = session_email(get_session(conn)) ->
        assign(conn, :auth_email, email)

      true ->
        conn |> redirect(to: "/login") |> halt()
    end
  end

  def call(conn, :api) do
    cond do
      not enabled?() -> conn
      private_ip?(conn.remote_ip) -> conn
      session_email(get_session(conn)) -> conn
      true -> conn |> put_status(401) |> json(%{error: "unauthorized"}) |> halt()
    end
  end

  def on_mount(:require_auth, _params, session, socket) do
    cond do
      not enabled?() ->
        {:cont, socket}

      email = session_email(session) ->
        {:cont, Phoenix.Component.assign(socket, :auth_email, email)}

      true ->
        {:halt, Phoenix.LiveView.redirect(socket, to: "/login")}
    end
  end

  def private_ip?({127, _, _, _}), do: true
  def private_ip?({10, _, _, _}), do: true
  def private_ip?({172, b, _, _}) when b in 16..31, do: true
  def private_ip?({192, 168, _, _}), do: true
  def private_ip?({0, 0, 0, 0, 0, 0, 0, 1}), do: true

  def private_ip?({0, 0, 0, 0, 0, 0xFFFF, hi, lo}),
    do: private_ip?({div(hi, 256), rem(hi, 256), div(lo, 256), rem(lo, 256)})

  def private_ip?(_), do: false
end
