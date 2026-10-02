#!/usr/bin/env sh
# Runs on AI-prod-01 only. Produces a verified PostgreSQL backup before 0024.
set -eu

root=/opt/ai-outreach-system
stamp=20260824_1400
backup="$root/backups/pre_0024_${stamp}.dump"
umask 077

postgres_user=$(docker inspect ai-outreach-production-postgres-1 --format '{{range .Config.Env}}{{println .}}{{end}}' | sed -n 's/^POSTGRES_USER=//p' | head -n 1)
postgres_db=$(docker inspect ai-outreach-production-postgres-1 --format '{{range .Config.Env}}{{println .}}{{end}}' | sed -n 's/^POSTGRES_DB=//p' | head -n 1)
test -n "$postgres_user"
test -n "$postgres_db"
docker exec ai-outreach-production-postgres-1 pg_dump -U "$postgres_user" -Fc "$postgres_db" > "$backup"
test -s "$backup"
docker exec -i ai-outreach-production-postgres-1 pg_restore --list < "$backup" > /dev/null
stat -c '%n %s bytes' "$backup"
