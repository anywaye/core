
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

  const requireJwt = async (c: Context, next: Next): Promise<void> => {
    const token = c.req.header("Authorization") ?? "";
    const principal = await authenticate(token.replace(/^Bearer /, ""));

    c.set("principal", principal);
    await next();
  };

  return { requireJwt };
}

function principalOf(payload: Record<string, unknown>): Principal {
  return {
    sub: String(payload.sub),
    scope: typeof payload.scope === "string" ? payload.scope.split(/\s+/) : [],
    accountId: typeof payload.account_id === "string" ? payload.account_id : undefined,
    claims: payload,
  };
}