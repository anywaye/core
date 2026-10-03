defmodule PublicWeb.HealthController do
  @moduledoc """
  Liveness and readiness. This service holds no customer data and this is the
  whole of its surface, so every entry point in account_scope.yml is
  `accountScoped: false` and every one of them is true.
  """

  def healthz(conn, _params), do: json(conn, %{status: "ok"})

  def readyz(conn, _params), do: json(conn, %{status: "ok"})
end