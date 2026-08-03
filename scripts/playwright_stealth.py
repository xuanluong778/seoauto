"""
Stealth helpers for Playwright: fingerprint variance, init scripts, human-like input,
challenge detection, partial-render scoring, and optional JSON debug dumps.

Not a guarantee against all bot systems — raises cost for naive fingerprinters and
aligns traffic with typical real Chrome sessions.
"""

from __future__ import annotations

import json
import logging
import os
import random
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup

_LOGGER = logging.getLogger(__name__)

# Chrome-stable style UAs (rotated per context — do not rely on a single string).
CHROME_MOBILE_UA = (
    "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.6261.119 Mobile Safari/537.36"
)
CHROME_DESKTOP_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.6261.119 Safari/537.36"
)

# Raw HTTP snapshot uses same family as desktop stealth (avoids Googlebot-only mismatch).
RAW_HTML_STEALTH_UA = CHROME_DESKTOP_UA

STEALTH_INIT_SCRIPT = r"""
(() => {
  const safeDefine = (obj, prop, desc) => {
    try { Object.defineProperty(obj, prop, desc); } catch (e) {}
  };
  // navigator.webdriver — primary automation flag
  safeDefine(navigator, "webdriver", { get: () => undefined, configurable: true });
  // Minimal chrome object (some sites probe chrome.runtime)
  try {
    if (!window.chrome) window.chrome = {};
    if (!window.chrome.runtime) window.chrome.runtime = {};
  } catch (e) {}
  // Languages — match context locale
  safeDefine(navigator, "languages", {
    get: () => Object.freeze(["en-US", "en"]),
    configurable: true,
  });
  // Permissions.query — avoid leaking automation-only behaviour for notifications
  try {
    const orig = navigator.permissions && navigator.permissions.query;
    if (orig && typeof orig === "function") {
      navigator.permissions.query = function (parameters) {
        if (parameters && parameters.name === "notifications") {
          return Promise.resolve({ state: "denied", onchange: null });
        }
        return orig.call(navigator.permissions, parameters);
      };
    }
  } catch (e) {}
})();
"""

CHROMIUM_LAUNCH_ARGS: list[str] = [
    "--disable-blink-features=AutomationControlled",
    "--no-sandbox",
    "--disable-infobars",
    "--disable-dev-shm-usage",
]


def random_mobile_viewport() -> dict[str, int]:
    return {"width": random.randint(390, 430), "height": random.randint(800, 950)}


def random_desktop_viewport() -> dict[str, int]:
    return {"width": random.randint(1280, 1536), "height": random.randint(800, 960)}


def random_device_scale_factor(profile: str) -> float:
    if profile == "mobile":
        return float(random.choice([2.0, 2.5, 2.625, 3.0]))
    return float(random.choice([1.0, 1.25]))


def stealth_context_options(
    *,
    profile: str,
    java_script_enabled: bool = True,
) -> dict[str, Any]:
    """
    profile: "mobile" | "desktop" | "desktop_nojs"
    Returns kwargs for browser.new_context (Playwright sync).
    """
    if profile == "desktop_nojs":
        profile = "desktop"
        java_script_enabled = False

    if profile == "desktop":
        ua = CHROME_DESKTOP_UA
        vp = random_desktop_viewport()
        tz = random.choice(["America/New_York", "America/Chicago", "America/Los_Angeles"])
    else:
        ua = CHROME_MOBILE_UA
        vp = random_mobile_viewport()
        tz = random.choice(["America/New_York", "America/Chicago"])

    return {
        "user_agent": ua,
        "viewport": vp,
        "device_scale_factor": random_device_scale_factor("mobile" if profile == "mobile" else "desktop"),
        "locale": "en-US",
        "timezone_id": tz,
        "java_script_enabled": java_script_enabled,
        "permissions": [],
        "ignore_https_errors": False,
        "has_touch": profile == "mobile",
        "is_mobile": profile == "mobile",
    }


def profile_label(profile: str, java_script_enabled: bool) -> str:
    if profile == "desktop" and not java_script_enabled:
        return "desktop_nojs"
    return profile


def attach_stealth_listeners(
    page: Any,
    *,
    network_log: list[dict[str, Any]],
    js_errors: list[str],
) -> None:
    def on_response(response: Any) -> None:
        try:
            st = int(response.status or 0)
            url = str(response.url or "")
            if st >= 400:
                network_log.append(
                    {
                        "type": "http_error",
                        "url": url,
                        "status": st,
                        "ts": time.time(),
                    }
                )
        except Exception:
            pass

    def on_request_failed(request: Any) -> None:
        try:
            err = getattr(request, "failure", None)
            if callable(err):
                err = err()
            network_log.append(
                {
                    "type": "request_failed",
                    "url": str(request.url or ""),
                    "error": str(err) if err else "unknown",
                    "ts": time.time(),
                }
            )
        except Exception:
            pass

    def on_page_error(err: Any) -> None:
        try:
            js_errors.append(str(err)[:800])
        except Exception:
            pass

    page.on("response", on_response)
    page.on("requestfailed", on_request_failed)
    page.on("pageerror", on_page_error)


def human_like_interaction(page: Any, interaction_log: list[dict[str, Any]]) -> None:
    """Random mouse moves + staggered scroll + pauses (non-deterministic)."""
    try:
        for _ in range(random.randint(2, 4)):
            x = random.randint(8, min(420, 200 + random.randint(0, 220)))
            y = random.randint(8, min(700, 120 + random.randint(0, 400)))
            steps = random.randint(6, 14)
            page.mouse.move(x, y, steps=steps)
            interaction_log.append({"action": "mouse_move", "x": x, "y": y, "steps": steps, "ts": time.time()})
            time.sleep(random.uniform(0.2, 0.9))

        for round_i in range(random.randint(3, 7)):
            dy = random.randint(180, 520)
            page.evaluate(f"window.scrollBy(0, {dy})")
            interaction_log.append({"action": "scroll_by", "dy": dy, "round": round_i, "ts": time.time()})
            time.sleep(random.uniform(0.2, 1.2))

        time.sleep(random.uniform(0.35, 1.1))
        page.evaluate("window.scrollTo(0, Math.max(0, (document.body?.scrollHeight || 0) - 1))")
        interaction_log.append({"action": "scroll_end", "ts": time.time()})
        time.sleep(random.uniform(0.25, 0.8))
    except Exception as exc:
        interaction_log.append({"action": "interaction_error", "error": str(exc)[:300], "ts": time.time()})


def advanced_wait_after_navigation(page: Any, interaction_log: list[dict[str, Any]]) -> None:
    """domcontentloaded already done in goto — deepen readiness + random settle."""
    page.wait_for_selector("body", state="attached", timeout=20000)
    interaction_log.append({"action": "wait_body", "ts": time.time()})
    page.wait_for_function("document.readyState === 'complete'", timeout=25000)
    interaction_log.append({"action": "wait_document_complete", "ts": time.time()})
    time.sleep(random.uniform(0.8, 2.2))
    interaction_log.append({"action": "random_settle", "ts": time.time()})


def scroll_lazy_pass(page: Any, interaction_log: list[dict[str, Any]]) -> None:
    for i in range(random.randint(28, 44)):
        try:
            at_bottom = page.evaluate(
                """() => {
                    const sh = document.body ? document.body.scrollHeight : 0;
                    const y = window.scrollY || 0;
                    const vh = window.innerHeight || 0;
                    return sh > 0 && (y + vh >= sh - 6);
                }"""
            )
            if at_bottom:
                break
            page.evaluate(
                "window.scrollBy(0, Math.min(820, (document.body?.scrollHeight || 900) - window.scrollY))"
            )
            time.sleep(random.uniform(0.05, 0.14))
        except Exception:
            break
    interaction_log.append({"action": "lazy_scroll_pass", "ts": time.time()})


def detect_cloudflare_challenge(
    *,
    http_status: int,
    html: str,
    response_headers: dict[str, Any],
) -> tuple[bool, str | None]:
    h = (html or "").lower()
    hb = " ".join(f"{k}={v}" for k, v in (response_headers or {}).items()).lower()
    markers = (
        "checking your browser",
        "just a moment...",
        "just a moment",
        "cf-browser-verification",
        "__cf_chl_jschl_tk__",
        "ddos protection by cloudflare",
        "enable javascript and cookies to continue",
    )
    if any(m in h for m in markers) or "__cf_chl" in h:
        return True, "cloudflare_challenge"
    if "cf-ray" in hb or "__cf_bm" in hb:
        if http_status in (403, 503) or "challenge" in h or "cloudflare" in h[:8000]:
            return True, "cloudflare_challenge"
    return False, None


def detect_blocked_generic(
    *,
    http_status: int,
    html: str,
    response_headers: dict[str, Any],
) -> tuple[str, str | None]:
    """Returns crawl_status, block_reason (blocked | success)."""
    st = int(http_status or 0)
    if st == 403:
        return "blocked", "http_403"
    if st == 429:
        return "blocked", "http_429"

    cf, br = detect_cloudflare_challenge(http_status=st, html=html, response_headers=response_headers)
    if cf and br:
        return "blocked", br

    h = (html or "").lower()
    if any(
        x in h
        for x in (
            "g-recaptcha",
            "google.com/recaptcha",
            "hcaptcha.com",
            "h-captcha",
            "recaptcha/enterprise",
        )
    ):
        return "blocked", "captcha"

    return "success", None


def assess_partial_render(html: str) -> tuple[str, float]:
    """
    render_status: full | partial
    render_confidence: 0..1 (higher = more confident page looks complete)
    """
    if not (html or "").strip():
        return "partial", 0.15
    try:
        soup = BeautifulSoup(html, "html.parser")
        text = soup.get_text(" ", strip=True)
        title_el = soup.find("title")
        title_txt = (title_el.get_text(strip=True) if title_el else "") or ""
        h1_el = soup.find("h1")
        h1_txt = (h1_el.get_text(strip=True) if h1_el else "") or ""
        main_el = soup.find("main") or soup.find(id=lambda x: x and str(x).lower() in ("main", "content", "primary"))
        score = 1.0
        lt = len(text)
        if lt < 120:
            score -= 0.35
        elif lt < 400:
            score -= 0.18
        if not title_txt.strip():
            score -= 0.22
        if not h1_txt.strip():
            score -= 0.12
        if main_el is None:
            score -= 0.08
        conf = max(0.0, min(1.0, round(score, 3)))
        status = "full" if conf >= 0.72 else "partial"
        return status, conf
    except Exception:
        return "partial", 0.45


@dataclass
class StealthDebugSession:
    """Accumulate artifacts when STealth / crawl debug logging is enabled."""

    run_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    profiles: list[dict[str, Any]] = field(default_factory=list)
    interactions: list[dict[str, Any]] = field(default_factory=list)
    network: list[dict[str, Any]] = field(default_factory=list)

    def add_profile_record(self, rec: dict[str, Any]) -> None:
        self.profiles.append(rec)

    def extend_interactions(self, items: list[dict[str, Any]]) -> None:
        self.interactions.extend(items)

    def extend_network(self, items: list[dict[str, Any]]) -> None:
        self.network.extend(items)

    def flush(self, base_dir: Path | None) -> None:
        if not base_dir:
            return
        out = base_dir / f"run_{self.run_id}"
        out.mkdir(parents=True, exist_ok=True)
        (out / "stealth_profile.json").write_text(
            json.dumps(self.profiles, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (out / "interaction_log.json").write_text(
            json.dumps(self.interactions, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (out / "network_log.json").write_text(
            json.dumps(self.network, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        _LOGGER.info("Stealth debug artifacts written to %s", out)


def stealth_debug_enabled() -> bool:
    return os.getenv("STEALTH_DEBUG_LOG", "").lower() in ("1", "true", "yes") or os.getenv(
        "CRAWLER_DEBUG_LOG", ""
    ).lower() in ("1", "true", "yes")


def stealth_debug_dir() -> Path:
    root = Path(__file__).resolve().parents[2] / "data" / "crawl_debug"
    root.mkdir(parents=True, exist_ok=True)
    return root
