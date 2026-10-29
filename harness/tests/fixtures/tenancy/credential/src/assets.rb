
module Assets
  SQL = "select * from assets where checksum = $1 and account_id = $2"

  def self.find_by_checksum(checksum, account)
    DB.exec(SQL, checksum, account.account_id)
  end
end
