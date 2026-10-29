import { createJwtVerifier } from "./middleware/jwt";

export function createApp(options: AppOptions = {}): Hono<AuthEnv> {
  const app = new Hono<AuthEnv>();

  app.get("/healthz", (c) => c.json({ status: "ok" }));

  const jwt = options.jwt ? createJwtVerifier(options.jwt) : null;
  if (jwt) {
    app.use("/v1/*", async (c, next) => {
      if (c.get("principal")) return next();

      return jwt.requireJwt(c, next);
    });
  }

  if (jwt) {
    app.get("/v1/me", (c) => c.json(c.get("principal")));
  }

  app.get("/v1/things", requireAccount, (c) => c.json(c.get("accountId")));

  app.get("/readyz", (c) => c.json({ status: "ready" }));

  return app;
}