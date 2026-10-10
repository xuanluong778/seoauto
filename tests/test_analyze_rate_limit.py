"""Technical scan poll must not hit POST /analyze IP bucket (429)."""

from __future__ import annotations

from app.services.rate_limiter import check_request_rate_limit, clear_rate_limit


def test_get_technical_job_poll_is_not_rate_limited():
    ip = "203.0.113.77"
    clear_rate_limit(path_prefix="/analyze", client_ip=ip)
    job_path = "/analyze/technical/jobs/abc123"
    for _ in range(80):
        ok, rule = check_request_rate_limit(job_path, ip, method="GET")
        assert ok, rule
        assert rule is None


def test_post_analyze_still_rate_limited():
    ip = "203.0.113.88"
    clear_rate_limit(path_prefix="/analyze", client_ip=ip)
    blocked = False
    for _ in range(35):
        ok, rule = check_request_rate_limit("/analyze/technical/jobs", ip, method="POST")
        if not ok:
            blocked = True
            assert rule == "/analyze"
            break
    assert blocked, "POST /analyze/technical/jobs should share /analyze 30/hour bucket"


def test_post_analyze_technical_shares_analyze_bucket():
    ip = "203.0.113.99"
    clear_rate_limit(path_prefix="/analyze", client_ip=ip)
    for _ in range(30):
        ok, _ = check_request_rate_limit("/analyze/technical", ip, method="POST")
        assert ok
    ok, rule = check_request_rate_limit("/analyze/technical", ip, method="POST")
    assert not ok
    assert rule == "/analyze"
