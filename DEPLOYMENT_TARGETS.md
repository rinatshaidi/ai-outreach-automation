# Deployment targets — hard safety rules

Owner-confirmed on 2026-08-11.

## Allowed production host

- Host: `ai-prod-01`
- Public IPv4: `165.232.68.212`
- Purpose: the only server approved for application deployments.
- Isolation rule: every project must be a separate Docker Compose project with its own
  containers, network and persistent volumes.

## Protected host — never touch

- Host: `revpn-01`
- Public IPv4: `165.22.95.1`
- Purpose: VPN only.
- Hard rule: never connect to this host, deploy to it, modify it, restart it, inspect it via SSH,
  or use it as an application deployment target.

## AI Outreach deployment identity

- Compose project: `ai-outreach-production`
- Server directory: `/opt/ai-outreach-system`
- Secret directory: `/etc/ai-outreach-system`
- Initial loopback port: `127.0.0.1:8010`
- Database: dedicated PostgreSQL container and dedicated Docker volume; do not use the host
  PostgreSQL service or another project's database.

