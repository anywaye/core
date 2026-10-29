export function createJwtVerifier(options: JwtOptions): JwtVerifier {
  const requireJwt = async (c: Context<AuthEnv>, next: Next) => {
    const token = bearerToken(c.req.header("Authorization"));
    if (token === null) return problem(c, unauthorized("a bearer token is required"));

    const { payload } = await jwtVerify(token, options.keys, { algorithms: ["RS256"] });
    c.set("principal", principalOf(payload));
    await next();
  };

  return { requireJwt };
}

function principalOf(payload: Record<string, unknown>): Principal {
  return {
    sub: payload.sub,
    accountId: typeof payload.account_id === "string" && payload.account_id !== "" ? payload.account_id : undefined,
    claims: payload,
  };
}