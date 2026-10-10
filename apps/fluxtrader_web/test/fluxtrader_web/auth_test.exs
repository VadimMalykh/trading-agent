defmodule FluxTraderWeb.AuthTest do
  @moduledoc """
  Magic-link sign-in. What matters: off unless a whitelist is set (local stays open), nothing
  reachable from outside without a session when it is on, a link signs in once and only for a
  whitelisted address, and a known secret means nobody gets in rather than everybody.
  """
  use FluxTraderWeb.ConnCase, async: false

  alias FluxTraderWeb.Auth
  alias FluxTraderWeb.Auth.TokenStore

  @email "vadim.malykh@gmail.com"
  @public_ip {8, 8, 8, 8}

  setup do
    TokenStore.reset()
    on_exit(fn -> Application.delete_env(:fluxtrader_web, :auth) end)
    :ok
  end

  defp enable(extra \\ []) do
    test = self()

    Application.put_env(
      :fluxtrader_web,
      :auth,
      Keyword.merge(
        [
          allowed_emails: [@email],
          allow_dev_secret: true,
          base_url: "http://vm.example:4000",
          deliver: fn email, link -> send(test, {:mailed, email, link}) end
        ],
        extra
      )
    )
  end

  defp public(conn), do: %{conn | remote_ip: @public_ip}

  defp mailed_token do
    assert_received {:mailed, @email, "http://vm.example:4000/login/" <> token}
    token
  end

  describe "disabled (no whitelist — local)" do
    test "the plugs pass everything through", %{conn: conn} do
      assert Auth.status() == :disabled
      refute Auth.call(public(conn), :browser).halted
      refute Auth.call(public(conn), :api).halted
    end

    test "/login sends you to the dashboard", %{conn: conn} do
      assert redirected_to(get(conn, ~p"/login")) == "/"
    end
  end

  describe "enabled" do
    setup do
      enable()
      :ok
    end

    test "the UI redirects to /login without a session", %{conn: conn} do
      assert redirected_to(get(public(conn), ~p"/settings")) == "/login"
    end

    test "the API refuses outside callers but not the VM's own curl", %{conn: conn} do
      assert json_response(get(public(conn), ~p"/api/positions"), 401)

      conn = Plug.Test.init_test_session(conn, %{})
      refute Auth.call(%{conn | remote_ip: {127, 0, 0, 1}}, :api).halted
      refute Auth.call(%{conn | remote_ip: {172, 18, 0, 1}}, :api).halted
      assert Auth.call(%{conn | remote_ip: {172, 32, 0, 1}}, :api).halted
    end

    test "a link is mailed to a whitelisted address only, built from config", %{conn: conn} do
      conn = post(%{conn | host: "evil.example"}, ~p"/login", email: "x@y.z")
      assert html_response(conn, 200) =~ "If that address is allowed"
      refute_received {:mailed, _, _}

      post(build_conn(), ~p"/login", email: " Vadim.Malykh@Gmail.com ")
      assert is_binary(mailed_token())
    end

    test "a second request inside a minute is not mailed", %{conn: conn} do
      post(conn, ~p"/login", email: @email)
      _ = mailed_token()
      post(build_conn(), ~p"/login", email: @email)
      refute_received {:mailed, _, _}
    end

    test "the link signs in once, by POST, and the session opens the UI", %{conn: conn} do
      post(conn, ~p"/login", email: @email)
      token = mailed_token()

      # Opening the link (or a mail scanner prefetching it) only shows a button.
      shown = get(public(build_conn()), ~p"/login/#{token}")
      assert html_response(shown, 200) =~ "Sign in to FluxTrader"

      signed_in = post(public(build_conn()), ~p"/login/confirm", token: token)
      assert redirected_to(signed_in) == "/"
      assert get_session(signed_in, :auth_email) == @email

      session = %{"auth_email" => @email, "auth_at" => System.system_time(:second)}
      conn = public(build_conn()) |> Plug.Test.init_test_session(session)
      assert Auth.call(conn, :browser).assigns.auth_email == @email
      refute Auth.call(conn, :api).halted

      again = post(public(build_conn()), ~p"/login/confirm", token: token)
      assert redirected_to(again) == "/login"
      refute get_session(again, :auth_email)
    end

    test "a forged or expired session does not pass", %{conn: conn} do
      old = System.system_time(:second) - Auth.session_max_age() - 1

      for session <- [
            %{"auth_email" => "x@y.z", "auth_at" => System.system_time(:second)},
            %{"auth_email" => @email, "auth_at" => old},
            %{"auth_email" => @email}
          ] do
        assert Auth.call(public(conn) |> Plug.Test.init_test_session(session), :browser).halted
      end
    end

    test "a tampered token is refused" do
      assert Auth.consume("garbage") == {:error, :invalid}
    end
  end

  describe "enabled with the public dev secret" do
    test "nobody can sign in and nothing is mailed", %{conn: conn} do
      enable(allow_dev_secret: false)
      assert {:misconfigured, _} = Auth.status()

      assert html_response(get(conn, ~p"/login"), 200) =~ "Sign-in is disabled"
      post(build_conn(), ~p"/login", email: @email)
      refute_received {:mailed, _, _}

      session = %{"auth_email" => @email, "auth_at" => System.system_time(:second)}
      assert Auth.call(public(conn) |> Plug.Test.init_test_session(session), :browser).halted
    end
  end

  test "private_ip?/1" do
    for ip <- [{127, 0, 0, 1}, {10, 1, 2, 3}, {172, 17, 0, 1}, {192, 168, 1, 1}, {0, 0, 0, 0, 0, 0, 0, 1}],
        do: assert(Auth.private_ip?(ip))

    for ip <- [@public_ip, {172, 15, 0, 1}, {34, 18, 165, 230}, {0, 0, 0, 0, 0, 0xFFFF, 0x0808, 0x0808}],
        do: refute(Auth.private_ip?(ip))

    assert Auth.private_ip?({0, 0, 0, 0, 0, 0xFFFF, 0x7F00, 0x0001})
  end
end
