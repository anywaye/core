export async function requireAccount(request: Request): Promise<{ accountId: string }> {
  const token = request.headers.get("authorization") ?? "";
  const claims = await verify(token);
  return { accountId: claims.accountId };
}
