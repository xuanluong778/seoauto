# Index WARN — `ix_wordpress_publish_jobs_status_created`

**Status:** WARN (non-blocking for WAVE 3 INDEX_AUDIT gate)

## Before

Migration `ensure_wave3_db_indexes.py` attempts:

```sql
CREATE INDEX IF NOT EXISTS ix_wordpress_publish_jobs_status_created
ON wordpress_publish_jobs (status, created_at DESC);
```

## Root cause

Application DB user `digiseo` is **not the owner** of table `wordpress_publish_jobs`.
PostgreSQL returns: `must be owner of table wordpress_publish_jobs`.

## Fix options

1. **DBA / table owner** runs the DDL above (recommended for production).
2. **GRANT** ownership or `CREATE` on the table to `digiseo` (if policy allows).
3. **Accept fallback** — existing index `ix_wordpress_publish_jobs_status_retry` covers
   worker claim/retry hot path; status+created ordering is a nice-to-have for admin lists.

## After (current state)

| Index | Present |
|-------|---------|
| `ix_wordpress_publish_jobs_status_created` | **No** (WARN) |
| `ix_wordpress_publish_jobs_status_retry` | **Yes** |

INDEX_AUDIT gate uses `ix_wordpress_publish_jobs_status_retry` as required critical index.
