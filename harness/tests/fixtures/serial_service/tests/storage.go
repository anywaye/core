
package storage

import (
	"context"
	"os"

	"github.com/jackc/pgx/v5/pgxpool"
)

func Pool(ctx context.Context) *pgxpool.Pool {
	dsn := os.Getenv("TEST_DATABASE_URL")
	pool, err := pgxpool.New(ctx, dsn)
	if err != nil {
		panic(err)
	}
	return pool
}