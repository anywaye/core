# Phoenix, copied from courier at the commit fleet.yml records for it. The handler
# is a `Controller, :action` pair, NOT a call, which is why the middleware is in a
# `pipeline` above the route and why `scoping-bypassed` cannot fire here without
# reporting courier's own router as unscoped.
  get "/webhook_endpoints", WebhookEndpointsController, :index
