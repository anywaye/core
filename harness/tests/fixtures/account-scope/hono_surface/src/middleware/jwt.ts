// The JWT gate, read out of guard's `src/middleware/jwt.ts` with the names and the
// order it uses there, because a fixture that renamed `requireJwt` or moved
// `principalOf` would be testing a symbol this fleet does not write.
//
// `principalOf` is the only place in this repository that turns a credential into
// an account, and `accountFrom.line` in `account_scope.yml` points at the line
// that reads the claim. That is what `account-key-lost` checks, so the claim and
// the line naming it are the same line by construction here — a fixture that put
// them apart would be able to go red for a reason it never measured.

type Next = () => Promise<void>;

export type JwtOptions = {
  issuer: string;
  audience: string;
};

export type Principal = {
  sub: string;
  scope: string[];
  accountId?: string;
  claims: Record<string, unknown>;
};

export type Context = {
  req: { header: (name: string) => string | undefined };
  get: (key: string) => unknown;
  set: (key: string, value: unknown) => void;
};

export function createJwtVerifier(): {
  requireJwt: (c: Context, next: Next) => Promise<void>;
} {
  async function authenticate(token: string): Promise<Principal> {
    return principalOf({ sub: token, account_id: token });
  }

  // The gate. A bearer token is verified and the principal is put on the request
  // context before any route behind it is entered — which is the whole of why a
  // Hono route registered after an `app.use` is scoped.
  const requireJwt = async (c: Context, next: Next): Promise<void> => {
    const token = c.req.header("Authorization") ?? "";
    const principal = await authenticate(token.replace(/^Bearer /, ""));

    c.set("principal", principal);
    await next();
  };

  return { requireJwt };
}

// THE LINE THE DECLARATION NAMES. A token is an account rather than a user
// because a verified claim says so, and a non-string or empty claim is `undefined`
// rather than a default account: an absent claim must never resolve to somebody.
function principalOf(payload: Record<string, unknown>): Principal {
  return {
    sub: String(payload.sub),
    scope: typeof payload.scope === "string" ? payload.scope.split(/\s+/) : [],
    accountId: typeof payload.account_id === "string" ? payload.account_id : undefined,
    claims: payload,
  };
}