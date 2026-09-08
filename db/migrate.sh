#!/bin/sh
# Applies any migration not already recorded, so it is safe to run on every start.
set -eu

psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -q -c \
  "CREATE TABLE IF NOT EXISTS schema_migrations (name text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now());"

for file in /migrations/*.sql; do
    name=$(basename "$file")
    applied=$(psql "$DATABASE_URL" -tAc "SELECT 1 FROM schema_migrations WHERE name = '$name';")

    if [ "$applied" = "1" ]; then
        echo "skip    $name"
        continue
    fi

    echo "apply   $name"
    psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -q -f "$file"
    psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -q -c \
      "INSERT INTO schema_migrations (name) VALUES ('$name');"
done

echo "schema up to date"
