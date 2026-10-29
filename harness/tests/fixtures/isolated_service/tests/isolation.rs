
mod common;

#[tokio::test]
async fn an_asset_round_trips() {
    let pool = common::test_pool().await;
    common::truncate(&pool).await;

    sqlx::query("insert into assets (name) values ($1)")
        .bind("a")
        .execute(&pool)
        .await
        .expect("inserting");

    let count: (i64,) = sqlx::query_as("select count(*) from assets")
        .fetch_one(&pool)
        .await
        .expect("counting");

    assert_eq!(count.0, 1, "the asset this test created is the only one it sees");
}