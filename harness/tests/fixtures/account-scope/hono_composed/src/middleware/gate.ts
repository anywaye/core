import { requireJwt } from "./jwt";

export function accountGate(c: Context<AuthEnv>, next: Next) {
  return requireJwt(c, next);
}