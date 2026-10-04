// What `accountFrom.via` names, and the only place in this fixture that reads the
// account out of anything. Copied in shape from gateway's `src/middleware/jwt.ts`,
// where `principalOf` reads `payload.account_id` and the gate is mounted on `/v1/*`
// twenty-seven lines above the route it protects.
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
    // A non-string `account_id` is ignored rather than rejected: the token is still
    // a valid token, and a rate-limit key is a worse thing to lose than a
    // well-formed claim is to gain.
    accountId: typeof payload.account_id === "string" && payload.account_id !== "" ? payload.account_id : undefined,
    claims: payload,
  };
}