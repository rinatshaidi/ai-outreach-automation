#!/usr/bin/env sh
# Requeues only today's failed automatic daily task after a provider recovery.
set -eu

postgres_container="ai-outreach-production-postgres-1"
postgres_user="$(docker exec "$postgres_container" sh -lc 'printf %s "$POSTGRES_USER"')"
postgres_db="$(docker exec "$postgres_container" sh -lc 'printf %s "$POSTGRES_DB"')"

docker exec "$postgres_container" \
  psql -U "$postgres_user" -d "$postgres_db" -v ON_ERROR_STOP=1 -c \
  "UPDATE search_tasks
   SET status = 'RUNNING',
       current_stage = 'queued_for_execution',
       failure_code = NULL,
       failure_reason = NULL,
       completed_at = NULL
   WHERE source = 'daily'
     AND scheduled_for_date = DATE '2026-08-24'
     AND status = 'FAILED';"
