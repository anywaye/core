// A probe. Reachable without a credential, which is why it is declared
// `accountScoped: false` with the reason `public` and still declared at all.
export function GET() {
  return Response.json({ status: "ok" });
}
