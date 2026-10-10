"""WAVE 1 — Celery queue routing (multi-queue mode)."""

from __future__ import annotations

import os

import pytest


def test_task_routes_when_multi_queue_enabled(monkeypatch):
    monkeypatch.setenv("CELERY_MULTI_QUEUE", "1")
    from app.queue import celery_queues

    assert celery_queues.celery_multi_queue_enabled()
    assert celery_queues.queue_for_task("content_ai.run_bulk") == "content_ai"
    assert celery_queues.queue_for_task("wordpress.execute_publish_job") == "wordpress"
    assert celery_queues.queue_for_task("crawl.process_crawl_job") == "crawl"
    assert celery_queues.queue_for_task("email.automation_tick") == "email"
    assert celery_queues.queue_for_task("jobs.recover_queued") == "default"
    assert celery_queues.queue_for_task("unknown.task") == "default"

    cfg = celery_queues.build_celery_queue_config()
    assert "task_routes" in cfg
    assert len(cfg["task_queues"]) == 5


def test_legacy_single_queue_when_disabled(monkeypatch):
    monkeypatch.setenv("CELERY_MULTI_QUEUE", "0")
    from app.queue import celery_queues

    assert not celery_queues.celery_multi_queue_enabled()
    assert celery_queues.build_celery_queue_config() == {}


def test_celery_app_includes_queue_config(monkeypatch):
    monkeypatch.setenv("CELERY_MULTI_QUEUE", "1")
    from app.queue import celery_queues

    cfg = celery_queues.build_celery_queue_config()
    routes = cfg.get("task_routes") or {}
    assert routes.get("content_ai.run_bulk", {}).get("queue") == "content_ai"
    assert routes.get("crawl.process_crawl_job", {}).get("queue") == "crawl"
