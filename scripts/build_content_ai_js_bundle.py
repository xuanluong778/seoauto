#!/usr/bin/env python3
"""Concatenate Content AI JS into core + lazy Auto Update tab bundles."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS_DIR = ROOT / "static" / "js" / "content_ai"

CORE_PARTS = [
    "content-ai-state.js",
    "content-ai-editor.js",
    "content-ai-duplicate.js",
    "content-ai-seo-score.js",
    "content-ai-single.js",
    "content-ai-images.js",
    "content-ai-projects.js",
    "content-ai-bulk.js",
    "content-ai-publish.js",
]
AUTO_PART = "content-ai-auto-update.js"
BLOCK_EDITOR_PART = "cau-block-editor.js"
ASSISTANT_UI_PART = "cau-assistant-ui.js"

OUT_CORE = JS_DIR / "content-ai-app.js"
OUT_AUTO = JS_DIR / "content-ai-auto-update-tab.js"

CORE_FOOTER = """
    window.ContentAiShared = {
        byId: byId,
        apiFetch: apiFetch,
        authJsonHeaders: authJsonHeaders,
        getAuthToken: getAuthToken,
        userStorageKey: userStorageKey,
        normalizeTargetBase: typeof normalizeTargetBase === "function" ? normalizeTargetBase : null,
    };
})();
"""

AUTO_HEADER = """/* Auto-generated Auto Update tab — load only when tab opens */
(() => {
    const _S = window.ContentAiShared || {};
    const byId = _S.byId || ((id) => document.getElementById(id));
    const apiFetch = _S.apiFetch || ((url, opts) => fetch(url, opts));
    const authJsonHeaders = _S.authJsonHeaders || (() => ({ "Content-Type": "application/json" }));
    const getAuthToken = _S.getAuthToken || (() => "");
    const userStorageKey = _S.userStorageKey || ((k) => k);
    const normalizeTargetBase = _S.normalizeTargetBase || ((url) => String(url || "").replace(/\\/[^/]*$/, ""));
"""


def main() -> None:
    chunks: list[str] = []
    for name in CORE_PARTS:
        path = JS_DIR / name
        if not path.is_file():
            raise SystemExit(f"Missing part: {path}")
        chunks.append(path.read_text(encoding="utf-8"))
    body = "\n".join(chunks)
    header = "/* Auto-generated — run scripts/build_content_ai_js_bundle.py after editing split files */\n"
    OUT_CORE.write_text(header + body + CORE_FOOTER, encoding="utf-8")
    print(f"Wrote {OUT_CORE} ({(header + body + CORE_FOOTER).count(chr(10))} lines)")

    auto_path = JS_DIR / AUTO_PART
    block_path = JS_DIR / BLOCK_EDITOR_PART
    asst_path = JS_DIR / ASSISTANT_UI_PART
    if not auto_path.is_file():
        raise SystemExit(f"Missing part: {auto_path}")
    if not block_path.is_file():
        raise SystemExit(f"Missing part: {block_path}")
    if not asst_path.is_file():
        raise SystemExit(f"Missing part: {asst_path}")
    auto_body = auto_path.read_text(encoding="utf-8")
    block_body = block_path.read_text(encoding="utf-8")
    asst_body = asst_path.read_text(encoding="utf-8")
    if not auto_body.rstrip().endswith("})();"):
        raise SystemExit("auto-update.js expected to end with })();")
    out_auto = block_body + "\n" + asst_body + "\n" + AUTO_HEADER + "\n" + auto_body
    OUT_AUTO.write_text(out_auto, encoding="utf-8")
    print(f"Wrote {OUT_AUTO} ({out_auto.count(chr(10))} lines)")


if __name__ == "__main__":
    main()
