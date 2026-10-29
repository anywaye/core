import { Hono } from "hono";
import type { Context } from "hono";
import { createJwtVerifier, type AuthEnv, type JwtOptions } from "./middleware/jwt";
import { liveness, sessionStatus } from "./status";

export type AppOptions = {
  jwt?: JwtOptions;
};

export function createApp(options: AppOptions = {}): Hono<AuthEnv> {
  const app = new Hono<AuthEnv>();

  app.get("/healthz", (c) => c.json(liveness()));

  const jwt = options.jwt ? createJwtVerifier() : null;
  if (jwt) {
    app.use("/v1/*", async (c, next) => {
      if (c.get("principal")) return next();

      return jwt.requireJwt(c, next);
    });
  }

  if (jwt) {
    app.get("/v1/me", (c) => c.json(c.get("principal")));
  }

  app.get("/ops/diagnostics", requireJwt(jwt), (c) => c.json(c.get("principal")));

  app.get("/auth/session", (c) => c.json(sessionStatus()));

  app.get("/v1/ready", (c) => c.json(liveness()));

  app.notFound((c) => c.json({ error: "not_found" }, 404));
}

export { createJwtVerifier };
export type { Context };