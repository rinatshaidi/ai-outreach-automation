#!/usr/bin/env sh
# Deploy primary-match orchestration. No schema, secret, Gmail or delivery changes.
set -eu

root=/opt/ai-outreach-system
release="$root/releases/20261001_primary_match"
package="$root/packages/ai-outreach-primary-match-20261001.tar.gz"
env_path=/etc/ai-outreach-system/production.env
previous=$(readlink -f "$root/current")
stamp=$(date -u +%Y%m%d_%H%M%S)
backup="$root/backups/pre_primary_match_${stamp}.dump"

test -f "$package"
test -f "$env_path"
test ! -e "$release"
umask 077

postgres_user=$(docker inspect ai-outreach-production-postgres-1 --format '{{range .Config.Env}}{{println .}}{{end}}' | sed -n 's/^POSTGRES_USER=//p' | head -n 1)
postgres_db=$(docker inspect ai-outreach-production-postgres-1 --format '{{range .Config.Env}}{{println .}}{{end}}' | sed -n 's/^POSTGRES_DB=//p' | head -n 1)
test -n "$postgres_user"
test -n "$postgres_db"
docker exec ai-outreach-production-postgres-1 pg_dump -U "$postgres_user" -Fc "$postgres_db" > "$backup"
test -s "$backup"
docker exec -i ai-outreach-production-postgres-1 pg_restore --list < "$backup" >/dev/null

mkdir -p "$release"
cp -a "$previous"/. "$release"/
tar -xzf "$package" -C "$release"

rollback() {
  cd "$previous"
  docker compose --env-file "$env_path" -f compose.production.example.yaml up -d --build --force-recreate --no-deps app worker
}

if ! (
  cd "$release"
  docker compose --env-file "$env_path" -f compose.production.example.yaml up -d --build --force-recreate --no-deps app worker
  for _ in 1 2 3 4 5 6 7 8 9 10 11 12; do
    if docker compose --env-file "$env_path" -f compose.production.example.yaml ps --status running app worker | grep -q app \
      && docker compose --env-file "$env_path" -f compose.production.example.yaml ps --status running app worker | grep -q worker \
      && curl -fsS http://127.0.0.1:8000/api/v1/health/ready >/dev/null; then
      exit 0
    fi
    sleep 5
  done
  exit 1
); then
  rollback
  exit 1
fi

ln -sfn "$release" "$root/current"
printf 'backup=%s\nrelease=%s\n' "$backup" "$release"
