defmodule PublicWeb.Router do
  use PublicWeb, :router

  pipeline :api do
    plug :accepts, ["json"]
  end

  scope "/", PublicWeb do
    pipe_through :api

    get "/healthz", HealthController, :healthz
    get "/readyz", HealthController, :readyz
    get "/version", VersionController, :show
  end
end