defmodule Liar.Unsubscribes do
  @moduledoc """
  Folds an unsubscribe into the suppression table.


  An unsubscribe has no principal, so there is no account to record. Writing the
  answer into a table that has an `account_id` would mean naming the account that
  sent the mail, which is a tenancy claim made for a mailbox somebody else chose.
  So the table this module writes has no `account_id` at all, and the sentence
  above mentioning `account_id` is the only occurrence of the word in this file.

  The module is one hop away from `LiarWeb.UnsubscribeController`, which is why it
  is in the fixture: a one-hop search that counted prose would report this route
  as account-scoped, and it is not.
  """

  def unsubscribe(token) when is_binary(token), do: {:ok, :recorded}

  def unsubscribe(_token), do: {:error, :unknown_token}
end