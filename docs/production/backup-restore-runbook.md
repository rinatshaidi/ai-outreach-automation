# PostgreSQL backup and restore runbook

Status: design only. The restore procedure must first run against an isolated disposable database,
never against the working production database.

## Targets

- Initial RPO: 24 hours.
- Initial RTO: 4 hours.
- Backup format: PostgreSQL custom-format `pg_dump`.
- Encryption: required before off-host transfer.
- Suggested initial retention: 7 daily + 4 weekly copies, pending legal approval.
- Restore proof: before production acceptance and at least monthly during the pilot.

## Backup procedure

The exact Compose/project names are selected at deployment time. Do not place database passwords
in the command line or report.

1. Resolve a new timestamped destination outside the database volume.
2. Confirm Alembic current/head and record the revision.
3. Run `pg_dump --format=custom --no-owner --no-acl` from the PostgreSQL container or an approved
   PostgreSQL client.
4. Require process exit code 0.
5. Require file size greater than zero.
6. Run `pg_restore --list` and require exit code 0.
7. Calculate SHA-256.
8. Encrypt with the approved owner-controlled key.
9. Copy the encrypted artifact to the approved off-host destination.
10. Verify remote size/checksum and record only non-secret metadata.
11. Apply the retention policy only after a verified newer backup exists.

Required evidence:

- backup identifier/path without credentials;
- created timestamp;
- source environment and Alembic revision;
- size;
- SHA-256 of the encrypted artifact;
- `pg_dump` and `pg_restore --list` outcomes;
- off-host verification outcome;
- retention class and expiry date.

## Isolated restore test

1. Select a verified encrypted backup.
2. Create a new isolated PostgreSQL database/container with a unique disposable name.
3. Ensure it is not connected to the production application and has no public port.
4. Decrypt into a protected temporary location.
5. Run `pg_restore --clean=false --no-owner --no-acl` into the empty isolated database.
6. Require exit code 0.
7. Verify Alembic revision.
8. Compare table counts and critical relationships using a read-only verification script/query.
9. Start an isolated application instance only if UI smoke is part of the test.
10. Record RTO and verification results without PII.
11. Stop and remove only the explicitly identified disposable restore resources.
12. Securely remove the temporary decrypted artifact according to host policy.

## Restore acceptance

- [ ] Backup decrypted successfully.
- [ ] `pg_restore` completed successfully.
- [ ] Alembic revision matches the backup metadata.
- [ ] Owner/profile, structured records, companies, contacts, drafts, approvals and audit counts
  match expected backup counts.
- [ ] Foreign-key and critical workflow links are intact.
- [ ] Application health/read-only smoke passes if tested.
- [ ] Measured restore time is within RTO.
- [ ] Production database and volumes were never targeted.

## Production recovery rule

Do not restore over the only working database. Restore into a new database, validate it, stop
writes, take an incident backup, and switch the application only after explicit owner approval.

