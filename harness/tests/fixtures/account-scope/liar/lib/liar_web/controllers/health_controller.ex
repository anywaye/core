defmodule LiarWeb.HealthController do
  @moduledoc """
  Liveness and readiness. Nothing here reaches a customer row, and nothing here
  mentions an account — not even in prose, because the point of this file in the
  fixture is that a genuinely public route has no account evidence ANYWHERE.
  """

  def healthz(conn, _params), do: json(conn, %{status: "ok"})

  def readyz(conn, _params), do: json(conn, %{status: "ok"})
end