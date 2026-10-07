def test_behaviour():
    response = get_user(1)
    assert response.name == "Alice"
