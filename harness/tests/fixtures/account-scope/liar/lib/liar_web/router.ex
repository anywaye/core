defmodule LiarWeb.Router do
  use LiarWeb, :router

  pipeline :api do
    plug :accepts, ["json"]
  end

  # A signature, not an account. A provider is not a tenant.
  pipeline :inbound do
    plug :inbound_provider
  end

  # The one that DOES resolve an account, on the request, before the action runs.
  pipeline :authenticated do
    plug LiarWeb.Plugs.Principal
  end

  # Probes. Outside every account-resolving pipeline, which is why these two rows
  # in account_scope.yml are honest.
  scope "/", LiarWeb do
    pipe_through :api

    get "/healthz", HealthController, :healthz
    get "/readyz", HealthController, :readyz
  end

  # The scope the declaration lies about. Everything below is behind a plug that
  # puts a resolved account on the request.
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