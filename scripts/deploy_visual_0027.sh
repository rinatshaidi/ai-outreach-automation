#!/usr/bin/env sh
# Deploys the Bolt-inspired presentation layer. No schema or data changes.
set -eu

root=/opt/ai-outreach-system
release="$root/releases/20260824_0027"
package="$root/packages/ai-outreach-0027-bolt-visual.tar.gz"
env_path=/etc/ai-outreach-system/production.env

test -f "$package"
test -f "$env_path"
test ! -e "$release"
mkdir -p "$release"
cp -a "$root/current"/. "$release"/
tar -xzf "$package" -C "$release"

cd "$release"
docker compose --env-file "$env_path" -f compose.production.example.yaml \
  up -d --build --no-deps app
ln -sfn "$release" "$root/current"
docker compose --env-file "$env_path" -f compose.production.example.yaml ps app
