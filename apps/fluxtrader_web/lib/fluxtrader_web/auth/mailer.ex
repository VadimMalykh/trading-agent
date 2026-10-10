defmodule FluxTraderWeb.Auth.Mailer do
  @moduledoc """
  Delivers the sign-in link: through Resend's HTTP API when `RESEND_API_KEY` is set (no SMTP
  dependency, the existing Finch pool), otherwise into the app log — which is also how local
  testing with auth switched on works (`docker compose logs app | grep "sign-in link"`).

  Resend's shared sender `onboarding@resend.dev` delivers only to the Resend account's own
  address; that is enough while the whitelist is that one address. Another recipient needs a
  verified domain and `AUTH_EMAIL_FROM` on it.

  Tests swap the delivery for a function: `config :fluxtrader_web, :auth, deliver: fun/2`.
  """
  require Logger

  @url "https://api.resend.com/emails"

  def deliver_link(email, link) do
    config = Application.get_env(:fluxtrader_web, :auth, [])

    cond do
      fun = config[:deliver] -> fun.(email, link)
      key = config[:resend_api_key] -> resend(key, config[:from], email, link)
      true -> Logger.warning("auth: no RESEND_API_KEY — sign-in link for #{email}: #{link}")
    end
  end

  defp resend(key, from, email, link) do
    body =
      Jason.encode!(%{
        from: from || "FluxTrader <onboarding@resend.dev>",
        to: [email],
        subject: "FluxTrader sign-in link",
        text:
          "Sign in to FluxTrader:\n\n#{link}\n\n" <>
            "The link works once, for #{div(FluxTraderWeb.Auth.token_max_age(), 60)} minutes. " <>
            "If you did not ask for it, ignore this mail."
      })

    headers = [{"authorization", "Bearer " <> key}, {"content-type", "application/json"}]

    case Finch.build(:post, @url, headers, body)
         |> Finch.request(FluxTrader.Finch, receive_timeout: 10_000) do
      {:ok, %{status: status}} when status in 200..299 ->
        :ok

      {:ok, %{status: status, body: body}} ->
        Logger.warning("auth: Resend refused the sign-in mail: #{status} #{body}")

      {:error, reason} ->
        Logger.warning("auth: Resend request failed: #{inspect(reason)}")
    end
  end
end
