
from .support_fake import FakePool


def test_a_row_round_trips_and_is_cleaned_up() -> None:
    pool = FakePool()
    pool.execute("insert into vault_secrets (id) values ($1)", ("a",))
    assert "a" in pool.rows

    pool.execute("delete from vault_secrets where id = $1", ("a",))
    assert "a" not in pool.rows
