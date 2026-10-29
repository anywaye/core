export function GET(request: Request, context: RouteContext): Promise<Response> {
  return handle(request, context);
}