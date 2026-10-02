#!/usr/bin/env sh
# Applies a code-only correction to the 0024 daily discovery release.
set -eu

root=/opt/ai-outreach-system
release="$root/releases/20260824_0024c"
package="$root/packages/ai-outreach-0024-daily-discovery.tar.gz"
test -f "$package"
test ! -e "$release"
mkdir -p "$release"
cp -a "$root/current"/. "$release"/
tar -xzf "$package" -C "$release"
runtime_env=$(mktemp)
trap 'rm -f "$runtime_env"' EXIT

{
  docker inspect ai-outreach-production-app-1 --format '{{range .Config.Env}}{{println .}}{{end}}'
  docker inspect ai-outreach-production-postgres-1 --format '{{range .Config.Env}}{{println .}}{{end}}'
  printf '%s\n' 'TRUSTED_PROXY_IPS=127.0.0.1,172.19.0.1'
} > "$runtime_env"
chmod 600 "$runtime_env"

cd "$release"
docker compose --env-file "$runtime_env" -f compose.production.example.yaml up -d --build --no-deps app worker
ln -sfn "$release" "$root/current"
docker compose --env-file "$runtime_env" -f compose.production.example.yaml ps app worker
