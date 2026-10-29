defmodule LiarWeb.Router do
  use LiarWeb, :router

  pipeline :api do
    plug :accepts, ["json"]
  end

  pipeline :inbound do
    plug :inbound_provider
  end

  pipeline :authenticated do
    plug LiarWeb.Plugs.Principal
  end

  scope "/", LiarWeb do
    pipe_through :api

    get "/healthz", HealthController, :healthz
    get "/readyz", HealthController, :readyz
  end

  scope "/v1", LiarWeb do
    pipe_through [:api, :authenticated]

    get "/webhook_endpoints", WebhookEndpointsController, :index
    get "/webhook_endpoints/:id", WebhookEndpointsController, :show
    get "/notification_preferences/:user_id", NotificationPreferencesController, :show
    put "/notification_preferences/:user_id", NotificationPreferencesController, :update
    post "/messages", MessagesController, :create
  end

  scope "/inbound", LiarWeb do
    pipe_through [:api, :inbound]

    post "/resend", InboundController, :create
  end

  scope "/unsubscribe", LiarWeb do
    pipe_through :api

    get "/:token", UnsubscribeController, :show
    post "/:token", UnsubscribeController, :create
  end
end