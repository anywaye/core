defmodule LiarWeb.InboundController do
  @moduledoc """
  A provider's signed webhook. A provider is not a tenant: it signs a body and
  sends no token, so there is no account on this request and none to resolve.

  The `account_id` below is prose about the suppression table, and the code names
  no account — which is what a correct `reason: unauthenticated-callback` looks
  like when a checker actually reads the file instead of counting words in it.
  """

  def create(conn, params) do
    case Inbound.verified_body(conn, params) do
      {:ok, body} -> json(conn, Inbound.apply(body))
      {:error, _reason} -> json(conn, %{error: "bad_signature"})
    end
  end
end