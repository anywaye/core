// A Hono app that COMPOSES another one, which is the second way a gate leaves the
// file its route is registered in. `app.route("/v1", v1())` mounts a whole sub-
// application, so what runs in front of `/me` is `api.use("/*", accountGate)` in
// src/api.ts, reaching `requireJwt` through src/middleware/gate.ts — two hops and a
// mount, and the row that names `requireJwt` is CORRECT.
//
// This is the case that decides what a checker does when it CANNOT read the chain.
// Answering "I cannot see it, so the route is unscoped" is the wolf; answering
// "I cannot see it" is `Recogniser.carries_handler`'s own answer for a chain that is
// not on the line, and it is the only one of the two that is ever right.
//
// `app.route` IS ALSO axum's `.route(path, handler)`, and this checker reads it as a
// registration — so this fixture also reports `undeclared: axum registers /v1`. That
// is a real and separate defect, measured, and it is LEFT IN rather than written
// around: a fixture that used `app.mount` to dodge it would leave the next reader
// believing the collision does not exist. REPORT-core-hono-inline-01.md §7.
import { v1 } from "./api";

export function createApp(): Hono<AuthEnv> {
  const app = new Hono<AuthEnv>();

  app.get("/healthz", (c) => c.json({ status: "ok" }));

  app.route("/v1", v1());

  return app;
}