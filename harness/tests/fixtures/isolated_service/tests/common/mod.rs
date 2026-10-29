
use std::sync::Arc;

use sqlx::postgres::PgPoolOptions;
use uuid::Uuid;

pub const SCHEMA_PREFIX: &str = "t_";
pub const SCHEMA_HEX_CHARS: usize = 8;

pub fn fresh_schema() -> String {
    let hex = Uuid::new_v4().simple().to_string();
    format!("{SCHEMA_PREFIX}{}", &hex[..SCHEMA_HEX_CHARS])
}

pub fn quoted(name: &str) -> String {
    format!("\"{name}\"")
}

pub async fn test_pool() -> Arc<sqlx::PgPool> {
    let schema = fresh_schema();
    let search_path = format!("set search_path to {}", quoted(&schema));

    let pool = PgPoolOptions::new()
        .max_connections(5)
        .after_connect(move |conn, _meta| {
            let search_path = search_path.clone();
            Box::pin(async move {
                sqlx::query(&search_path).execute(&mut *conn).await?;
                Ok(())
            })
        })
        .connect(&test_database_url())
        .await
        .expect("TEST_DATABASE_URL");

    let name = quoted(&schema);
    sqlx::query(&format!("create schema {name}"))
        .execute(&pool)
        .await
        .expect("creating the test schema");
    pool
}

pub async fn truncate(pool: &sqlx::PgPool) {
    sqlx::query("truncate assets, asset_variants cascade")
        .execute(pool)
        .await
        .expect("truncate");
}

fn test_database_url() -> String {
    std::env::var("TEST_DATABASE_URL").expect("TEST_DATABASE_URL is not set")
}