defmodule ExampleWeb.Router do
  use ExampleWeb, :router

  pipeline :browser do
    plug :accepts, ["html"]
  end

  scope "/", ExampleWeb do
    pipe_through :browser

    get "/healthz", HealthController, :healthz
  end

  scope "/v1", ExampleWeb do
    pipe_through :api

    get "/messages", MessagesController, :index
    post "/messages", MessagesController, :create
    get "/messages/:id", MessagesController, :show
  end

  scope "/inbound", ExampleWeb do
    pipe_through :api

    post "/resend", InboundController, :create
  end
end
