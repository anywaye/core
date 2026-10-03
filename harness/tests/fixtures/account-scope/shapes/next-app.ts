// Next.js' App Router, copied from site at the commit fleet.yml records for it, and
// the case that made `path_from_filename` a field rather than an afterthought: the
// path is in the FILE'S NAME. `app/v1/[...path]/route.ts` serves `/v1/{path}` and
// exports GET, POST, PATCH and DELETE as named functions with nothing in any line
// saying what it is. A recogniser that required the path in the line would read
// this repository as having NO ROUTES AT ALL — which is D18's `route_defs=0`,
// reproduced by the checker written to prevent it.
export function GET(request: Request, context: RouteContext): Promise<Response> {
  return handle(request, context);
}