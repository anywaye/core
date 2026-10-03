// The sub-application src/index.ts mounts. Its own gate is `accountGate`, and
// `accountGate` is what calls `requireJwt` — so neither this file nor the one the
// route is registered in says the word `requireJwt`, and a checker reading only
// either of them would call a correct route unscoped.
import { accountGate } from "./middleware/gate";

export function v1(): Hono<AuthEnv> {
  const api = new Hono<AuthEnv>();

  api.use("/*", accountGate);

  api.get("/me", (c) => c.json(c.get("principal")));

  return api;
}