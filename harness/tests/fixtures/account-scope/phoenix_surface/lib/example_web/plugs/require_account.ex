defmodule ExampleWeb.Plugs.RequireAccount do
  import Plug.Conn
  alias Example.Accounts

  @doc """
  Resolves the caller's account from the bearer token. This is the line
  account_scope.yml's `accountFrom` names.
  """
  def require_account(conn, _opts) do
    case Accounts.resolve(conn.assigns[:token]) do
      {:ok, account_id} -> assign(conn, :current_account_id, account_id)
      {:error, reason} -> ExampleWeb.Problem.halt(conn, reason)
    end
  end
end
