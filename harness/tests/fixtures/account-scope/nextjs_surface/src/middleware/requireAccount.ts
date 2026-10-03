// What `accountFrom.via` names. Two of this fleet's services resolve the caller's
// account here, and it is the SECOND control for the path-from-filename rule: the
// registration line says nothing about this symbol, so `scoping-bypassed` cannot
// fire — the same answer as Phoenix and axum, and for the same reason.
export async function requireAccount(request: Request): Promise<{ accountId: string }> {
  const token = request.headers.get("authorization") ?? "";
  const claims = await verify(token);
  return { accountId: claims.accountId };
}
