
require "test/unit"

class AssetsTenancyTest < Test::Unit::TestCase
  ACCOUNT = "6f5d4c3b-2a19-4e8f-9c07-1b2d3e4f5061"
  OTHER_ACCOUNT = "7a6e5d4c-3b20-4f90-8d18-2c3e4f506172"

  def setup
    Assets.insert(id: "a1", account_id: ACCOUNT, checksum: "sha256:mine")
    Assets.insert(id: "b1", account_id: OTHER_ACCOUNT, checksum: "sha256:theirs")
  end

  def account(id)
    Account.new(id)
  end

  def test_fetch_is_absent_without_an_account
    assert Assets.fetch("a1", account(nil)).nil?
  end

  def test_fetch_is_absent_for_another_account
    assert Assets.fetch("a1", account(OTHER_ACCOUNT)).nil?
  end

  def test_fetch_sees_its_own_row
    assert_equal "sha256:mine", Assets.fetch("a1", account(ACCOUNT)).checksum
  end

  def test_list_is_empty_without_an_account
    assert Assets.list(account(nil)).empty?
  end

  def test_list_is_empty_for_another_account
    assert Assets.list(account(OTHER_ACCOUNT)).empty?
  end

  def test_list_sees_its_own_rows
    assert_equal "sha256:mine", Assets.list(account(ACCOUNT)).first.checksum
  end

  def test_pending_is_empty_without_an_account
    assert Assets.pending(account(nil)).empty?
  end

  def test_pending_is_empty_for_another_account
    assert Assets.pending(account(OTHER_ACCOUNT)).empty?
  end

  def test_pending_sees_its_own_window
    assert_equal "pending", Assets.pending(account(ACCOUNT)).first.status
  end

  def test_settle_changes_nothing_without_an_account
    assert_unchanged("a1") { Assets.settle("a1", account(nil)) }
  end

  def test_settle_changes_nothing_for_another_account
    assert_unchanged("a1") { Assets.settle("a1", account(OTHER_ACCOUNT)) }
  end

  def test_settle_changes_its_own_row
    assert_changed("a1") { Assets.settle("a1", account(ACCOUNT)) }
  end

  def test_delete_changes_nothing_without_an_account
    assert_unchanged("a1") { Assets.delete("a1", account(nil)) }
  end

  def test_delete_changes_nothing_for_another_account
    assert_unchanged("a1") { Assets.delete("a1", account(OTHER_ACCOUNT)) }
  end

  def test_delete_removes_its_own_row
    assert_deleted("a1") { Assets.delete("a1", account(ACCOUNT)) }
  end

  def test_variant_is_absent_without_an_account
    assert AssetVariants.fetch("v1", account(nil)).nil?
  end

  def test_variant_is_absent_for_another_account
    assert AssetVariants.fetch("v1", account(OTHER_ACCOUNT)).nil?
  end

  def test_variant_sees_its_own_row
    assert_equal "v1", AssetVariants.fetch("v1", account(ACCOUNT)).id
  end

  def test_find_by_checksum_is_absent_without_an_account
    assert Assets.find_by_checksum("sha256:mine", account(nil)).nil?
  end

  def test_find_by_checksum_is_absent_for_another_account
    assert Assets.find_by_checksum("sha256:mine", account(OTHER_ACCOUNT)).nil?
  end

  def test_find_by_checksum_sees_its_own_row
    assert_equal "a1", Assets.find_by_checksum("sha256:mine", account(ACCOUNT)).id
  end
end