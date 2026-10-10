defmodule FluxTraderWeb.AuthHTML do
  use FluxTraderWeb, :html

  @box "max-width:420px;margin:48px auto;background:#1a1a2e;border-radius:8px;padding:24px;"
  @input "width:100%;padding:10px;margin:12px 0;border-radius:6px;border:1px solid #333;background:#0f0f23;color:#e0e0e0;"
  @button "background:#e94560;color:white;border:none;padding:10px 20px;border-radius:6px;cursor:pointer;font-weight:bold;"

  defp style(:box), do: @box
  defp style(:input), do: @input
  defp style(:button), do: @button

  def new(assigns) do
    ~H"""
    <div style={style(:box)}>
      <h1 style="color:#e94560;margin-bottom:16px;">Sign in</h1>
      <%= cond do %>
        <% @misconfigured -> %>
          <p style="color:#e74c3c;">Sign-in is disabled: <%= @misconfigured %>.</p>
        <% @sent -> %>
          <p>If that address is allowed, a sign-in link is on its way. It works once, for 15 minutes.</p>
        <% true -> %>
          <form action={~p"/login"} method="post">
            <input type="hidden" name="_csrf_token" value={get_csrf_token()} />
            <input type="email" name="email" required autofocus placeholder="email" style={style(:input)} />
            <button type="submit" style={style(:button)}>Email me a link</button>
          </form>
      <% end %>
    </div>
    """
  end

  def confirm(assigns) do
    ~H"""
    <div style={style(:box)}>
      <h1 style="color:#e94560;margin-bottom:16px;">Sign in</h1>
      <form action={~p"/login/confirm"} method="post">
        <input type="hidden" name="_csrf_token" value={get_csrf_token()} />
        <input type="hidden" name="token" value={@token} />
        <button type="submit" style={style(:button)}>Sign in to FluxTrader</button>
      </form>
    </div>
    """
  end
end
