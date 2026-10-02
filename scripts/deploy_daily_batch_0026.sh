#!/usr/bin/env sh
# Deploys the durable daily-search time budget. No schema or data changes.
set -eu

root=/opt/ai-outreach-system
release="$root/releases/20260824_0026"
package="$root/packages/ai-outreach-0026-daily-batch.tar.gz"
env_path=/etc/ai-outreach-system/production.env
test -f "$package"
test -f "$env_path"
test ! -e "$release"
mkdir -p "$release"
cp -a "$root/current"/. "$release"/
tar -xzf "$package" -C "$release"

cd "$release"
docker compose --env-file "$env_path" -f compose.production.example.yaml \
  up -d --build --no-deps app worker
ln -sfn "$release" "$root/current"
docker compose --env-file "$env_path" -f compose.production.example.yaml ps app worker
