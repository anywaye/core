defmodule PublicWeb.VersionController do
  @moduledoc """
  The build's version. It answers from a compile-time constant and reaches
  nothing.
  """

  def show(conn, _params), do: json(conn, %{version: version()})

  defp version, do: "0.0.0"
end