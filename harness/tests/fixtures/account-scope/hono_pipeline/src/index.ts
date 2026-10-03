// Hono's pre-handler chain, copied from guard's `src/index.ts` and cut down to the
// one mount and the four routes this check needs.
//
// `app.use` is registered ABOVE the route, and Hono answers in registration order,
// so `/v1/me` IS behind `requireJwt` — and neither fact is visible on the line that
// registers it, which is the whole of what a checker that reads the registration
// line can see. The file's own comment at line 6 says the same thing:
//
//   "Hono matches handlers in registration order and a route registered before a
//    `use` answers first and never calls next."
import { createJwtVerifier } from "./middleware/jwt";

export function createApp(options: AppOptions = {}): Hono<AuthEnv> {
  const app = new Hono<AuthEnv>();

  // A probe, registered BEFORE the gate: nothing runs in front of it.
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

  // The OTHER shape, and the one that already worked: the gate is an argument ON
  // the registration line. Both have to stay decidable, or a checker that learned to
  // read the chain would have stopped reading the line.
  app.get("/v1/things", requireAccount, (c) => c.json(c.get("accountId")));

  // A probe BEHIND the gate whose own handler resolves no account. Being behind
  // `requireJwt` is not reaching another account's rows, and a check that said
  // otherwise would accuse every authenticated probe in the fleet.
  app.get("/readyz", (c) => c.json({ status: "ready" }));

  return app;
}