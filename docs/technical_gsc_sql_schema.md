# Proposed SQL schema — Technical Audit × GSC (future migration)

Hiện tại dữ liệu GSC được lưu trong `data/technical_audits.json` (field `gsc_summary`, `url_inspection_results`, …).
Khi migrate PostgreSQL, đề xuất các bảng sau.

## `technical_gsc_properties`

| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| user_id | INT FK users | |
| site_url | VARCHAR(512) | Property GSC chính thức |
| verified | BOOLEAN | |
| linked_at | TIMESTAMPTZ | |
| last_sync_at | TIMESTAMPTZ | |

## `technical_gsc_performance_daily`

| Column | Type | Notes |
|--------|------|-------|
| id | BIGSERIAL PK | |
| user_id | INT | |
| property_id | UUID FK | |
| date | DATE | |
| page_url | TEXT | |
| query | TEXT NULL | NULL = aggregate page-only |
| device | VARCHAR(16) NULL | |
| country | VARCHAR(8) NULL | |
| clicks | INT | |
| impressions | INT | |
| ctr | DECIMAL(8,6) | |
| position | DECIMAL(8,2) | |

Index: `(user_id, property_id, date, page_url)`

## `technical_gsc_url_inspections`

| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| user_id | INT | |
| property_id | UUID FK | |
| inspection_url | TEXT | |
| inspected_at | TIMESTAMPTZ | |
| index_verdict | VARCHAR(32) | PASS, FAIL, … |
| coverage_state | TEXT | |
| user_canonical | TEXT | |
| google_canonical | TEXT | |
| last_crawl_time | TIMESTAMPTZ NULL | |
| raw_json | JSONB | Full API response |

## `technical_audit_gsc_join`

| Column | Type | Notes |
|--------|------|-------|
| audit_id | UUID FK | Links to audit run |
| property_id | UUID FK | |
| gsc_summary_json | JSONB | Snapshot at audit time |
| confidence_overall | DECIMAL(4,3) | |
| partial_data | BOOLEAN | |
| created_at | TIMESTAMPTZ | |
