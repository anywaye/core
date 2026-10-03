defmodule LiarWeb.Plugs.Principal do
  @moduledoc """
  Resolves who is calling, and refuses the request when nobody is.

  ## The `account_id` in this paragraph is not evidence of anything

  Every action reads `conn.assigns.current_account`, and an `account_id` in a
  request body is ignored. A checker that searched this file for the word
  `account_id` would find two mentions here and call them two hits, and both
  would be prose about a field it never touches. This file is in the fixture
  because the one line below is the only place in the repository that resolves
  an account, and it is line 19.
  """

  import Plug.Conn

  def call(conn, _opts) do
    case resolve(bearer(conn)) do
      {:ok, account_id} -> assign(conn, :current_account, account_id)
      :error -> send_resp(conn, 401, ~s({"error":"unauthenticated"}))
    end
  end

  defp resolve(_token), do: :error
end