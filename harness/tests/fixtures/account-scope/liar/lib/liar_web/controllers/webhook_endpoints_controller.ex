defmodule LiarWeb.WebhookEndpointsController do
  @moduledoc """
  The JSON API over webhook endpoints, every action behind `:authenticated`.

  The account comes from `conn.assigns.current_account` and never from the body —
  an `account_id` in a request is ignored, and the two mentions of that field in
  this moduledoc are prose. The three below are code.
  """

  def index(conn, params) do
    account_id = conn.assigns.current_account

    json(conn, %{data: Endpoints.page(account_id, params["limit"])})
  end

  def show(conn, %{"id" => id}) do
    json(conn, %{data: Endpoints.get(id, conn.assigns.current_account)})
  end

  def create(conn, params) do
    attrs = %{url: params["url"], account_id: conn.assigns.current_account}

    case Endpoints.create(attrs) do
      {:ok, endpoint} -> json(conn, %{data: %{id: endpoint.id}})
      {:error, _reason} -> json(conn, %{error: "invalid"})
    end
  end
end