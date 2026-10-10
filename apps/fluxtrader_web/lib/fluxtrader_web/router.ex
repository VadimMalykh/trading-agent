defmodule FluxTraderWeb.Router do
  use FluxTraderWeb, :router

  pipeline :browser do
    plug :accepts, ["html"]
    plug :fetch_session
    plug :fetch_live_flash
    plug :put_root_layout, html: {FluxTraderWeb.Layouts, :root}
    plug :protect_from_forgery
    plug :put_secure_browser_headers
  end

  pipeline :api do
    plug :accepts, ["json"]
    # Only so a browser signed in on the VM can open /api/* too.
    plug :fetch_session
  end

  # Both no-ops unless AUTH_ALLOWED_EMAILS is set — see FluxTraderWeb.Auth.
  pipeline :require_auth do
    plug FluxTraderWeb.Auth, :browser
  end

  pipeline :require_api_auth do
    plug FluxTraderWeb.Auth, :api
  end

  scope "/", FluxTraderWeb do
    pipe_through :browser

    get "/login", AuthController, :new
    post "/login", AuthController, :create
    post "/login/confirm", AuthController, :confirm
    get "/login/:token", AuthController, :show
    get "/logout", AuthController, :delete
  end

  scope "/", FluxTraderWeb do
    pipe_through [:browser, :require_auth]

    live_session :authenticated, on_mount: {FluxTraderWeb.Auth, :require_auth} do
      live "/", DashboardLive, :index
      live "/settings", SettingsLive, :index
    end
  end

  scope "/api", FluxTraderWeb do
    pipe_through [:api, :require_api_auth]

    get "/positions", PositionController, :index
    get "/signals", SignalController, :index
    # Signal liveness, the policy's current coverage cut, and the paper A/B (M3_PLAN §0.8).
    get "/health", HealthController, :index
  end
end
