defmodule LiarWeb.UnsubscribeController do
  @moduledoc """
  `GET` and `POST /unsubscribe/:token`, behind no account-resolving pipeline.


  The authority of this route is a TOKEN in the path, not an account in a
  credential. There is no principal, so there is no account to resolve, and a
  declaration that claimed otherwise would be claiming a boundary this route does
  not have.

  It does hold customer data — a mailbox — so it is the hard negative control: a
  check that fired on "this handler reaches customer data" would be right about
  the fact and wrong about the verdict, and that is the false positive this fixture
  exists to keep out. What separates it is that no account is EVER resolved on the
  request, not that the data is harmless.

  The `account_id` mentions below are prose, and `Liar.Unsubscribes` carries the
  same prose in its own moduledoc, so a one-hop search for account evidence finds
  prose on both sides and no code on either.
  """

  alias Liar.Unsubscribes

  def show(conn, _params), do: unsubscribe(conn)

  def create(conn, _params), do: unsubscribe(conn)

  defp unsubscribe(conn) do
    case Unsubscribes.unsubscribe(conn.path_params["token"]) do
      {:ok, _outcome} -> json(conn, %{data: %{status: "unsubscribed"}})
      {:error, _reason} -> json(conn, %{data: %{status: "not_found"}})
    end
  end
end