import { v1 } from "./api";

export function createApp(): Hono<AuthEnv> {
  const app = new Hono<AuthEnv>();

  app.get("/healthz", (c) => c.json({ status: "ok" }));

  app.route("/v1", v1());

  return app;
}