defmodule LiarWeb.NotificationPreferencesController do
  @moduledoc """
  One user's notification preferences, per account.


  This controller contains the word `account_id` exactly twice, and both are
  prose in this moduledoc. The code never writes it: it reads
  `conn.assigns.current_account` and passes the value on. A checker that grepped
  for `account_id` here would find two hits and neither would be a fact about the
  code, and a checker that grepped for `current_account` would find the two lines
  that are. Both spellings are in the signal for that reason, and only a search
  over CODE rather than prose gets the right answer on this file.
  """

  def show(conn, params) do
    preferences = Preferences.list(conn.assigns.current_account, params["user_id"])

    json(conn, %{data: preferences})
  end

  def update(conn, params) do
    case Preferences.update(conn.assigns.current_account, params["user_id"], params) do
      {:ok, preferences} -> json(conn, %{data: preferences})
      {:error, _reason} -> json(conn, %{error: "invalid"})
    end
  end
end