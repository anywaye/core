#[test]
fn behaviour() {
    let response = get_user(1);
    assert_eq!(response.name, "Alice");
}
