defmodule LiarWeb.MessagesController do
  @moduledoc """
  The one door into the send path.

  ## Why this controller is in the liar fixture

  This file contains the word `account_id` three times and **every one of them is
  prose**. Its code names no account at all: it validates a payload and hands it to
  `Messages.validate/1` and `Deliver.email/2`, and the account that scopes them was
  put on the request by a plug, before this function was entered.

  That is the case a search of the handler file cannot reach, and it is the case
  courier's real `MessagesController` is in. Reading the registration's PIPELINE is
  what catches it: `pipe_through [:api, :authenticated]` names a plug whose one
  account-resolving line is `principal.ex:19`.
  """

  def create(conn, params) do
    with {:ok, payload} <- Messages.validate(params),
         {:ok, result} <- Deliver.email(payload) do
      json(conn, %{data: %{id: result.id}})
    else
      {:error, _reason} -> json(conn, %{error: "invalid"})
    end
  end
end