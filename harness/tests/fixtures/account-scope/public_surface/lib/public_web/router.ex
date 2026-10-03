defmodule PublicWeb.Router do
  use PublicWeb, :router

  pipeline :api do
    plug :accepts, ["json"]
  end

  # Nothing below resolves an account, and nothing below reaches a customer row.
  scope "/", PublicWeb do
    pipe_through :api

    get "/healthz", HealthController, :healthz
    get "/readyz", HealthController, :readyz
    get "/version", VersionController, :show
  end
end