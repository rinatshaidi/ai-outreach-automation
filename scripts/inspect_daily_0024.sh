#!/usr/bin/env sh
set -eu

postgres_container="ai-outreach-production-postgres-1"
postgres_user="$(docker exec "$postgres_container" sh -lc 'printf %s "$POSTGRES_USER"')"
postgres_db="$(docker exec "$postgres_container" sh -lc 'printf %s "$POSTGRES_DB"')"

docker exec "$postgres_container" \
  psql -U "$postgres_user" -d "$postgres_db" -At -F '|' -c \
  "SELECT source, scheduled_for_date, status, found_count, accepted_count, COALESCE(current_stage, ''), COALESCE(failure_reason, '')
   FROM search_tasks
   WHERE source = 'daily'
   ORDER BY created_at DESC
   LIMIT 1;"

docker exec "$postgres_container" \
  psql -U "$postgres_user" -d "$postgres_db" -At -F '|' -c \
  "SELECT 'profile', profile_status, COUNT(*)
   FROM candidate_profiles
   GROUP BY profile_status
   ORDER BY profile_status;"

docker exec "$postgres_container" \
  psql -U "$postgres_user" -d "$postgres_db" -At -F '|' -c \
  "SELECT 'preferences',
          jsonb_array_length(COALESCE(desired_roles, '[]'::jsonb)),
          jsonb_array_length(COALESCE(preferred_industries, '[]'::jsonb)),
          jsonb_array_length(COALESCE(preferred_countries, '[]'::jsonb))
   FROM candidate_profiles
   LIMIT 1;"
