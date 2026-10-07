defmodule BehaviourTest do
  use ExUnit.Case

  test "a behaviour test that asserts on the product" do
    response = MyApp.Users.get_user(1)
    assert response.name == "Alice"
  end
end
