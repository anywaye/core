// The gate the sub-application mounts, and the hop between it and the verifier. Two
// hops is where `hono_pipeline` stops and this fixture starts: the mount in
// src/index.ts, the gate here, and the verifier in ./jwt.
import { requireJwt } from "./jwt";

export function accountGate(c: Context<AuthEnv>, next: Next) {
  return requireJwt(c, next);
}