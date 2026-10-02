#!/usr/bin/env bash
# Runs only on AI-prod-01. Stores a key for company discovery, not AI rewrite.
set -euo pipefail

readonly env_path="/etc/ai-outreach-system/production.env"
readonly project_dir="/opt/ai-outreach-system/current"
temporary_path=""
openai_key=""

cleanup() {
  openai_key=""
  if [[ -n "${temporary_path}" && -f "${temporary_path}" ]]; then
    rm -f -- "${temporary_path}"
  fi
}
trap cleanup EXIT

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Run this helper as root on ai-prod-01." >&2
  exit 1
fi
test -f "${env_path}"

IFS= read -r openai_key
while [[ "${openai_key}" == $'\r'* || "${openai_key}" == $'\n'* ]]; do openai_key="${openai_key:1}"; done
while [[ "${openai_key}" == *$'\r' || "${openai_key}" == *$'\n' ]]; do openai_key="${openai_key::-1}"; done

case "${openai_key}" in
  sk-proj-*|sk-svcacct-*|sk-*) ;;
  *) echo "The key has an unsupported prefix; nothing changed." >&2; exit 1 ;;
esac
if [[ -z "${openai_key}" || "${openai_key}" =~ [[:space:][:cntrl:]] ]]; then
  echo "The key is empty or contains whitespace/control characters; nothing changed." >&2
  exit 1
fi

umask 077
temporary_path="$(mktemp /etc/ai-outreach-system/production.env.XXXXXX)"
grep -Ev '^(OPENAI_API_KEY|OPENAI_COMPANY_DISCOVERY_ENABLED|DAILY_DISCOVERY_ENABLED|DAILY_DISCOVERY_HOUR|DAILY_DISCOVERY_RESULT_LIMIT|GMAIL_SYNC_ENABLED)=' \
  "${env_path}" > "${temporary_path}"
printf '%s\n' \
  'OPENAI_API_KEY='"${openai_key}" \
  'OPENAI_COMPANY_DISCOVERY_ENABLED=true' \
  'DAILY_DISCOVERY_ENABLED=true' \
  'DAILY_DISCOVERY_HOUR=9' \
  'DAILY_DISCOVERY_RESULT_LIMIT=5' \
  'GMAIL_SYNC_ENABLED=false' >> "${temporary_path}"
install -o root -g root -m 0600 "${temporary_path}" "${env_path}"
openai_key=""

cd "${project_dir}"
docker compose --env-file "${env_path}" -f compose.production.example.yaml \
  up -d --force-recreate app worker >/dev/null 2>&1
echo "OPENAI_API_KEY=configured"
