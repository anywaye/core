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