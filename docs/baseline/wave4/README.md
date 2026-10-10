# WAVE 4 — WordPress Publish Worker

**Result:** `WAVE_4_WORDPRESS_PUBLISH = FULL PASS`
**Snapshot:** 2026-09-02T03:56:55.798239+00:00

## Remote idempotency

- Payload gửi WordPress: `request_id` + `idempotency_key`
- Mapping lưu: `wordpress_request_idempotency` (`publish:post_create:{request_id}` → `post_id`)
- Timeout/mất response: probe `GET /wp-json/seoauto/v1/posts/by-request-id/{request_id}`
- Plugin trả `seoauto_article_exists` + `post_id`: finalize success, không tạo bài mới

## Gates

- BEAT_RESTART_NO_DUPLICATE: **PASS**
- CELERY_BEAT_SINGLETON: **PASS**
- KNOWN_FAILURES_NOT_INCREASED: **PASS**
- REMOTE_WP_IDEMPOTENCY: **PASS**
- UI_API_REGRESSION: **PASS**
- WP_CREDIT_IDEMPOTENCY: **PASS**
- WP_DUPLICATE: **PASS**
- WP_IDEMPOTENCY: **PASS**
- WP_PUBLISH: **PASS**
- WP_RESPONSE_LOST_AFTER_SUCCESS: **PASS**
- WP_RETRY_AFTER_REMOTE_SUCCESS: **PASS**
- WP_RETRY_RECOVERY: **PASS**
- WP_SCHEDULE: **PASS**
- WP_SINGLE_SCHEDULER: **PASS**
- WP_TENANT_ISOLATION: **PASS**

## Ops evidence

- Celery Beat processes: 1 (online 1)
- Default queue depth: 0
- Beat tick latency: 1943.2 ms

