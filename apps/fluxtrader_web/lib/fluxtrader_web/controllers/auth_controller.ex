defmodule FluxTraderWeb.AuthController do
  @moduledoc "The magic-link pages. See `FluxTraderWeb.Auth`."
  use FluxTraderWeb, :controller

  alias FluxTraderWeb.Auth

  def new(conn, _params) do
    case Auth.status() do
      :disabled -> redirect(conn, to: ~p"/")
      status -> render(conn, :new, misconfigured: misconfigured(status), sent: false)
    end
  end

  def create(conn, %{"email" => email}) do
    Auth.request_link(email)
    render(conn, :new, misconfigured: misconfigured(Auth.status()), sent: true)
  end

  def create(conn, _params), do: redirect(conn, to: ~p"/login")

  # GET only shows a button: mail scanners prefetch links, and a GET that signed in would let
  # them spend the single-use token before Vadim clicks it.
  def show(conn, %{"token" => token}), do: render(conn, :confirm, token: token)

  def confirm(conn, %{"token" => token}) do
    case Auth.consume(token) do
      {:ok, email} ->
        conn |> Auth.log_in(email) |> redirect(to: ~p"/")

      {:error, _} ->
        conn
        |> put_flash(:error, "That link is invalid, expired or already used. Ask for a new one.")
        |> redirect(to: ~p"/login")
    end
  end

  def delete(conn, _params), do: conn |> Auth.log_out() |> redirect(to: ~p"/login")

  defp misconfigured({:misconfigured, reason}), do: reason
  defp misconfigured(_), do: nil
end
