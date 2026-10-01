# DB-07 synthetic seed run report

## Result

- **Seed payloads:** `../tenant_site/seed.json` creates the inactive `tenant-demo` directory and two inactive sites (`site-a` / `凤凰谷`, `site-b` / `第二站`). `seed.json` creates the nine exact-name Phoenix Valley catalog items and one pending, unpublished draft version per item. The second site receives no customer, resource, ledger, or service catalog rows.
- **Isolation evidence:** the in-memory SQLite fixture places synthetic probe rows only at site-a. Reads resolved to site-b return zero rows for customer/resource/ledger; trying to select site-a from site-b's resolved scope raises `SiteScopeDenied`.
- **Publication/booking gate:** all nine versions have `approval_status=pending`, `publication_status=unpublished`, and `status=draft`. Price, currency, duration, eligibility, qualifications, location, capacity, preparation, on-site rules, cancellation policy, and effective date are null. Every version is rejected by the publication and booking guards.
- **History/recovery:** the test preserves a retired version's synthetic appointment snapshot after inserting a new draft version. Rollback refuses referenced versions atomically; an unreferenced seed rollback followed by reapply recreates byte-equivalent managed rows.
- **Safety:** tests use only the standard library and an in-memory SQLite database. No application DDL, production database connection, dependency installation, real customer data, or live write was used.

## Commands

| Command | Exit | Machine result |
| --- | ---: | --- |
| `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s domain/seeds/health_service_catalog/tests -p 'test_*.py' -v` | 0 | 6 passed, 0 failed. |
| `python3 scripts/validate_plan_coverage.py --source-root /home/agent/code/jiankang_app_uniapp` | 0 | 6 PASS: 143 planned; 97/46 scope; 58 bidirectional registry links; 35+13 lanes; allowed status set; inventory mapping. |
| `git diff --check` | 0 | clean. |

The working tree changes for this run are limited to `domain/seeds/health_service_catalog/` and `domain/seeds/tenant_site/`. The implementation-track `tasks.json`, baseline `backend/tasks.json`, and `/home/agent/code/progress.md` were not edited.
