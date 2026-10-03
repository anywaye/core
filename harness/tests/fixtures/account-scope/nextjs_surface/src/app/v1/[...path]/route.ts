// The Next.js App Router surface, on the shape `site` and `parlor` both serve.
//
// The catch-all is the point: `app/v1/[...path]/route.ts` handles the whole `/v1`
// surface and exports GET, POST, PATCH and DELETE as named functions, so the
// declaration names ONE entry point per method against a path the file's own name
// carries. A checker that needed the path in the line would read this as no routes
// at all, which is D18's `route_defs=0` reproduced by the tool written to stop it.
import type { RouteContext } from "./types";

export function GET(request: Request, context: RouteContext): Promise<Response> {
  return dispatch(request, context);
}

export function POST(request: Request, context: RouteContext): Promise<Response> {
  return dispatch(request, context);
}

export function PATCH(request: Request, context: RouteContext): Promise<Response> {
  return dispatch(request, context);
}

export function DELETE(request: Request, context: RouteContext): Promise<Response> {
  return dispatch(request, context);
}