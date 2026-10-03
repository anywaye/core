// A probe. Same reason, and the reason a reader must be able to check for
// themselves rather than infer.
export function GET() {
  return Response.json({ status: "ready" });
}
