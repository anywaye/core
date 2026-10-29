import { accountGate } from "./middleware/gate";

export function v1(): Hono<AuthEnv> {
  const api = new Hono<AuthEnv>();

  api.use("/*", accountGate);

  api.get("/me", (c) => c.json(c.get("principal")));

  return api;
}