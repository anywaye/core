# assets.rb — the repository the HTTP layer calls. One module, one query, one
# bind. There is no path through here that reads a row without being told which
# account is asking, which is the property tenancy.yml's bind entry point names.

module Assets
  # The tenant key, bound rather than interpolated: a reader can see the
  # placeholder and cannot turn it into a second account's value.
  SQL = "select * from assets where checksum = $1 and account_id = $2"

  def self.find_by_checksum(checksum, account)
    DB.exec(SQL, checksum, account.account_id)
  end
end
