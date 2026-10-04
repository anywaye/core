// A Hono gateway, MEASURED out of gateway's `src/index.ts` rather than invented:
// the route shapes, the middleware spelling and the gate below it are the ones
// that repository actually registers, which is the same rule
// `fixtures/account-scope/shapes/hono.ts` follows and for the same reason — a
// pattern whose only example is its author's idea of a route is a pattern that
// will match something it was not written for.
//
// TWO THINGS about this file are the whole point of the fixture, and neither can
// be written any other way without changing what is being measured:
//
//   * the account gate is an `app.use("/v1/*", …)` registered TWELVE LINES above
//     the route it governs — twenty-seven in gateway's own file, which is the number
//     that decided the case. Hono matches handlers in registration order, so a
//     route registered after a `use` is behind it, and the route's OWN line says
//     nothing about scoping either way;
//   * `/v1/me`'s registration carries an INLINE handler that reads the principal
//     off the request context and resolves no account of its own.
//
// So for `/v1/me` the registration line is silent about scoping and the file's
// earlier lines are not. That is the one shape `scoping-bypassed` could not read
// at all — and `declaration-contradicts-code` can, because with an inline handler
// the handler IS the registration line, which is the same fact read from the other
// side.
//
// THE TWO `if (jwt) { … }` BLOCKS ARE THE SAME NUMBER OF LINES ON PURPOSE. Cases 39
// and 40 of the red proof break this file by commenting the gate out and by
// swapping the two blocks, and a breakage that shifted every line below it would
// turn `scoping-bypassed` into `stale` and prove nothing about the gate. Both
// breakages here are exactly line-count preserving.
import { Hono } from "hono";
import type { Context } from "hono";
import { createJwtVerifier, type AuthEnv, type JwtOptions } from "./middleware/jwt";
import { liveness, sessionStatus } from "./status";

export type AppOptions = {
  jwt?: JwtOptions;
};

export function createApp(options: AppOptions = {}): Hono<AuthEnv> {
  const app = new Hono<AuthEnv>();

  // Liveness is unconditional and touches nothing; a dependency outage must not
  // get the process restarted out from under in-flight requests.
  app.get("/healthz", (c) => c.json(liveness()));

  // Mounted on the prefix rather than per route: a new /v1 route is authenticated
  // unless somebody deliberately does otherwise, and forgetting to is not a
  // failure mode this gateway should have.
  //
  // The ordering is load-bearing rather than tidy. Hono matches handlers in
  // registration order and a route registered before a `use` answers first and
  // never calls `next` — a gate mounted after the route it exists to guard is a
  // gate that does not run.
  const jwt = options.jwt ? createJwtVerifier() : null;
  if (jwt) {
    app.use("/v1/*", async (c, next) => {
      if (c.get("principal")) return next();

      return jwt.requireJwt(c, next);
    });
  }

  if (jwt) {
    // The route that proves the chain is wired: no behaviour of its own, and it
    // forwards nothing. It resolves no account — it READS one the gate put on
    // the request context twelve lines above, and `c.get("principal")` on this
    // line is that gate's doing and not this route's.
    app.get("/v1/me", (c) => c.json(c.get("principal")));
  }

  // A route behind NO gate, scoped through its OWN registration line instead. It
  // is here so the fixture holds a route the gate cannot be credited for: a
  // checker that accepted any `use` above a route would pass this one for the
  // wrong reason, and this row is what proves it did not.
  app.get("/ops/diagnostics", requireJwt(jwt), (c) => c.json(c.get("principal")));

  // A public route that resolves nothing at all.
  app.get("/auth/session", (c) => c.json(sessionStatus()));

  // A probe BEHIND the gate. `/v1/ready` is registered after `app.use("/v1/*", …)`
  // and so is behind `requireJwt`, and it resolves no account of its own. Being
  // behind an account gate is not reaching another account's rows, and a check that
  // said otherwise would accuse every authenticated probe in the fleet — courier's
  // measured `/readyz` case, with a different path in front of it.
  app.get("/v1/ready", (c) => c.json(liveness()));

  app.notFound((c) => c.json({ error: "not_found" }, 404));
}

export { createJwtVerifier };
export type { Context };