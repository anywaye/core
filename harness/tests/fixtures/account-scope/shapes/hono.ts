// Hono, copied from gateway at the commit fleet.yml records for it. `app.get` with a
// path literal and the handler as the second argument — the shape that makes
// `scoping-bypassed` decidable, because the handler IS on the registration line.
  app.get("/v1/me", (c) => c.json(c.get("principal")));
