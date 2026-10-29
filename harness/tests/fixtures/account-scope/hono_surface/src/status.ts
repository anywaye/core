
export function liveness(): { status: string } {
  return { status: "ok" };
}

export function sessionStatus(): { ok: boolean } {
  return { ok: true };
}