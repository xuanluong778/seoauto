# WAVE 9 — Observability issues log

Snapshot: 2026-09-03T01:39:53.207353+00:00

## before → issue → fix → alert test → after

### API metrics
- **before:** /metrics had http latency only
- **issue:** Missing SLO, alerts, auth/LLM counters
- **fix:** Extended collect_ops_metrics + RequestIdMiddleware + ops_alerting
- **alert test:** simulate_alert_test fired 8 alerts
- **after:** PASS

### Structured logging
- **before:** Plain access logs, secrets could leak
- **issue:** No request_id correlation; token/password in logs
- **fix:** structured_log.py + RequestIdMiddleware JSON lines with redaction
- **alert test:** pytest test_secret_redaction + test_structured_log_no_secrets
- **after:** PASS

### Alert dedup / recovery
- **before:** No alert pipeline
- **issue:** Risk of alert spam on sustained incidents
- **fix:** ops_alerting dedup TTL + recovery_state_snapshot
- **alert test:** dedup=True recovery=True
- **after:** PASS

### DB / Redis / Queue
- **before:** Probes only on /ready
- **issue:** No pool/queue depth in /metrics dashboard
- **fix:** redis_queue_stats, pg_connection_stats, queue_backlog in /metrics
- **alert test:** ALERT_DB_REDIS + ALERT_QUEUE_BACKLOG simulation
- **after:** DB=PASS REDIS=PASS

## All gates PASS
