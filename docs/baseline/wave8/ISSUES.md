# WAVE 8 — Security findings (ISSUE → ROOT_CAUSE → FIX → ATTACK TEST → AFTER)

## 1. Audit log IP spoof via XFF

| Field | Detail |
|-------|--------|
| ISSUE | `security_audit_log._client_ip` trusted client-supplied X-Forwarded-For |
| ROOT_CAUSE | Raw header parse without trusted-proxy peer check |
| FIX | Use `resolve_client_ip()` from `app/services/trusted_proxy.py` |
| ATTACK TEST | Spoof XFF from untrusted peer — audit row must record direct peer, not spoof |
| AFTER | PASS — `test_audit_log_ip_uses_trusted_proxy` |

## 2. JWT server-side revocation + short-lived access

| Field | Detail |
|-------|--------|
| ISSUE | Stateless 720h JWT — logout cookie-only, no revoke, stolen token valid 30 days |
| ROOT_CAUSE | No server-side session store |
| FIX | `SERVER_SESSIONS_ENABLED=1` — 20m access JWT + refresh rotation + `user_sessions` PG table |
| ATTACK TEST | logout/refresh-reuse/password-change/role-downgrade/disable → 401 |
| AFTER | PASS — `tests/test_wave8_session_auth.py` |

## 3. Cross-tenant IDOR (service + HTTP)

| Field | Detail |
|-------|--------|
| ISSUE | Risk of ID swap on project/audit/job/generation |
| ROOT_CAUSE | Must enforce user_id/org at every read path |
| FIX | Existing `get_*_for_user` patterns verified; live attack matrix |
| ATTACK TEST | Tenant B token → Tenant A resource IDs → 401/403/404 |
| AFTER | PASS — all probes blocked |

## 4. Redis cache isolation

| Field | Detail |
|-------|--------|
| ISSUE | Shared cache keys could leak tenant data |
| ROOT_CAUSE | Key design must include user_id + org_id |
| FIX | `biz:v*:` hashed tenant keys; `dup:wp:v*:{user_id}:` corpus keys |
| ATTACK TEST | Set cache for user A — user B key miss |
| AFTER | PASS |

## 5. Celery forged payload

| Field | Detail |
|-------|--------|
| ISSUE | Worker could trust payload user_id |
| ROOT_CAUSE | Message body not authoritative |
| FIX | `get_job_for_user` checks DB row ownership columns |
| ATTACK TEST | Job owned by u1 with payload user_id=u2 — u2 cannot read |
| AFTER | PASS |

## 6. Webhook replay (SePay)

| Field | Detail |
|-------|--------|
| ISSUE | Duplicate webhook could double-credit |
| ROOT_CAUSE | Idempotency on transaction_id |
| FIX | Existing `sepay_webhook_service` replay handling |
| ATTACK TEST | `tests/test_sepay_webhook.py::test_webhook_replay_same_tx_idempotent_with_auth` |
| AFTER | PASS — pytest |

## 7. SSRF / upload / error leak

| Field | Detail |
|-------|--------|
| ISSUE | Internal URL fetch, fake MIME upload, stack in 500 |
| ROOT_CAUSE | Defense in depth at url_safety, media_storage, safe_errors |
| FIX | Existing guards + regression pytest |
| ATTACK TEST | metadata URL blocked; .png with JPEG bytes rejected; 500 generic message |
| AFTER | PASS |
