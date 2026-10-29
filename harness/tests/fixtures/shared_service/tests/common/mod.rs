
use sqlx::postgres::PgPoolOptions;

pub async fn shared_pool() -> sqlx::PgPool {
    PgPoolOptions::new()
        .max_connections(5)
        .connect(&test_database_url())
        .await
        .expect("TEST_DATABASE_URL")
}

fn test_database_url() -> String {
    std::env::var("TEST_DATABASE_URL").expect("TEST_DATABASE_URL is not set")
}