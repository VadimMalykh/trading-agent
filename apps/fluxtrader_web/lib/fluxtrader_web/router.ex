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
  end

  scope "/", FluxTraderWeb do
    pipe_through :browser

    live "/", DashboardLive, :index
    live "/settings", SettingsLive, :index
  end

  scope "/api", FluxTraderWeb do
    pipe_through :api

    get "/positions", PositionController, :index
    get "/signals", SignalController, :index
    # Signal liveness, the policy's current coverage cut, and the paper A/B (M3_PLAN §0.8).
    get "/health", HealthController, :index
  end
end
