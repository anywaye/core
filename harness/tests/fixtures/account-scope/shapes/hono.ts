  app.get("/v1/me", (c) => c.json(c.get("principal")));
