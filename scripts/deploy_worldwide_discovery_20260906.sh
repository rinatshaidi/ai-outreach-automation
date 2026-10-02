#!/usr/bin/env sh
# Deploys the worldwide-discovery geography correction and safely requalifies
# today's already researched daily results. No mail settings are changed.
set -eu

root=/opt/ai-outreach-system
release="$root/releases/20260906_0001"
package="$root/packages/ai-outreach-worldwide-discovery-20260906.tar.gz"
env_path=/etc/ai-outreach-system/production.env
task_id=b791bf9c-8c0f-4dcc-ab4e-983f354e17f4
previous=$(readlink -f "$root/current")
stamp=$(date -u +%Y%m%d_%H%M%S)
backup="$root/backups/pre_worldwide_discovery_${stamp}.dump"

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
  docker compose --env-file "$env_path" -f compose.production.example.yaml up -d --build --no-deps app worker
}

if ! (
  cd "$release"
  docker compose --env-file "$env_path" -f compose.production.example.yaml up -d --build --no-deps app worker
  for _ in 1 2 3 4 5 6; do
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

cd "$release"
docker compose --env-file "$env_path" -f compose.production.example.yaml \
  run --rm --no-deps app python scripts/requalify_worldwide_daily_results.py --task-id "$task_id"

ln -sfn "$release" "$root/current"
printf 'backup=%s\nrelease=%s\n' "$backup" "$release"
docker compose --env-file "$env_path" -f compose.production.example.yaml ps app worker
