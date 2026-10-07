# tenancy_test.rb — the negative assertions, and the three arms.
#
# Every entry point in tenancy.yml names THREE of these, and the third is the one
# with the information in it: the same call made by the account's OWN credential
# has to come back with the row. "An unauthenticated request fails" is
# satisfied by a service whose database is switched off, so it proves nothing;
# what proves isolation is that another account's VALID credential is refused
# while this one's is not.
#
# The two account fixtures below are the whole idiom: a second account, and the
# same question asked of both. For a write, "nothing" is the other account's row
# coming back unchanged — the refusal is an absent row, never a raised error.
#
# AND the assertion each arm needs is NOT the same for all three, which is the
# part a service gets wrong. A `USING` clause that filters the row out raises
# NOTHING and matches zero rows, so a read denial is asserted as an empty
# result; a `WITH CHECK` violation raises 42501, so a write denial is asserted
# as an exception. Asserting an exception on the read arm is asserting a
# privilege failure and passing for the wrong reason, which is how a policy that
# admits every tenant gets a green test. docs/tenancy.md has the table.

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

  # no identity: nothing is acting at all, so nothing comes back
  def test_fetch_is_absent_without_an_account
    assert Assets.fetch("a1", account(nil)).nil?
  end

  # another tenant's VALID credential: the arm with all the information in it
  def test_fetch_is_absent_for_another_account
    assert Assets.fetch("a1", account(OTHER_ACCOUNT)).nil?
  end

  # its own: the row comes back, and with its own value rather than merely not raising
  def test_fetch_sees_its_own_row
    assert_equal "sha256:mine", Assets.fetch("a1", account(ACCOUNT)).checksum
  end

  # the list, which is the one a join usually loses the scope on
  def test_list_is_empty_without_an_account
    assert Assets.list(account(nil)).empty?
  end

  def test_list_is_empty_for_another_account
    assert Assets.list(account(OTHER_ACCOUNT)).empty?
  end

  def test_list_sees_its_own_rows
    assert_equal "sha256:mine", Assets.list(account(ACCOUNT)).first.checksum
  end

  # the settlement window
  def test_pending_is_empty_without_an_account
    assert Assets.pending(account(nil)).empty?
  end

  def test_pending_is_empty_for_another_account
    assert Assets.pending(account(OTHER_ACCOUNT)).empty?
  end

  def test_pending_sees_its_own_window
    assert_equal "pending", Assets.pending(account(ACCOUNT)).first.status
  end

  # the update: another account's row is not even touched
  def test_settle_changes_nothing_without_an_account
    assert_unchanged("a1") { Assets.settle("a1", account(nil)) }
  end

  def test_settle_changes_nothing_for_another_account
    assert_unchanged("a1") { Assets.settle("a1", account(OTHER_ACCOUNT)) }
  end

  def test_settle_changes_its_own_row
    assert_changed("a1") { Assets.settle("a1", account(ACCOUNT)) }
  end

  # the delete, which is the one that would end a customer's data
  def test_delete_changes_nothing_without_an_account
    assert_unchanged("a1") { Assets.delete("a1", account(nil)) }
  end

  def test_delete_changes_nothing_for_another_account
    assert_unchanged("a1") { Assets.delete("a1", account(OTHER_ACCOUNT)) }
  end

  def test_delete_removes_its_own_row
    assert_deleted("a1") { Assets.delete("a1", account(ACCOUNT)) }
  end

  # the variant
  def test_variant_is_absent_without_an_account
    assert AssetVariants.fetch("v1", account(nil)).nil?
  end

  def test_variant_is_absent_for_another_account
    assert AssetVariants.fetch("v1", account(OTHER_ACCOUNT)).nil?
  end

  def test_variant_sees_its_own_row
    assert_equal "v1", AssetVariants.fetch("v1", account(ACCOUNT)).id
  end

  # the repository method, with the account bound rather than interpolated
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