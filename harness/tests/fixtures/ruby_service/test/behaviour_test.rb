require "minitest/autorun"

class BehaviourTest < Minitest::Test
  def test_behaviour
    response = get_user(1)
    assert_equal "Alice", response.name
  end
end
