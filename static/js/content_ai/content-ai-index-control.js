/**
 * Content AI ↔ Index Control — nút Kiểm tra Index / Gửi IndexNow sau khi tạo hoặc publish.
 */
(function (global) {
    "use strict";

    function isHttpUrl(url) {
        try {
            var u = new URL(String(url || "").trim());
            return u.protocol === "http:" || u.protocol === "https:";
        } catch (_) {
            return false;
        }
    }

    function extractDomain(urlOrSite) {
        var raw = String(urlOrSite || "").trim();
        if (!raw) return "";
        try {
            if (raw.indexOf("://") < 0) raw = "https://" + raw;
            return new URL(raw).hostname.replace(/^www\./i, "").toLowerCase();
        } catch (_) {
            return raw.replace(/^https?:\/\//i, "").split("/")[0].replace(/^www\./i, "").toLowerCase();
        }
    }

    function buildGuessUrl(targetWebsite, slug) {
        var base = String(targetWebsite || "").trim().replace(/\/+$/, "");
        var s = String(slug || "").trim().replace(/^\/+/, "");
        if (!base) return "";
        try {
            var href = base.indexOf("://") >= 0 ? base : "https://" + base;
            var u = new URL(href);
            if (s) u.pathname = "/" + s;
            return u.href;
        } catch (_) {
            return s ? base + "/" + s : base;
        }
    }

    function buildIndexControlUrl(opts) {
        opts = opts || {};
        var p = new URLSearchParams();
        p.set("tab", opts.tab || "check-free");
        if (opts.url && isHttpUrl(opts.url)) p.set("url", opts.url);
        return "/index-control?" + p.toString();
    }

    function showActions(opts) {
        opts = opts || {};
        var box = document.getElementById("caIndexControlActions");
        if (!box) return;

        var btnCheck = document.getElementById("caBtnCheckIndex");
        var btnIndexNow = document.getElementById("caBtnIndexNow");
        var hint = document.getElementById("caIndexControlHint");

        var publicUrl = opts.publicUrl && isHttpUrl(opts.publicUrl) ? String(opts.publicUrl).trim() : "";
        var guessUrl = opts.guessUrl && isHttpUrl(opts.guessUrl) ? String(opts.guessUrl).trim() : "";
        if (!guessUrl && opts.targetWebsite) {
            guessUrl = buildGuessUrl(opts.targetWebsite, opts.slug);
            if (!isHttpUrl(guessUrl)) guessUrl = "";
        }
        var articleUrl = publicUrl || guessUrl;
        var domain = extractDomain(opts.domain || publicUrl || guessUrl || opts.targetWebsite);
        var showIndexNow = !!(opts.published && publicUrl);

        box.hidden = false;

        if (btnCheck) {
            btnCheck.onclick = function () {
                global.location.href = buildIndexControlUrl({
                    tab: "check-free",
                    url: articleUrl
                });
            };
        }
        if (btnIndexNow) {
            btnIndexNow.hidden = !showIndexNow;
            btnIndexNow.onclick = showIndexNow
                ? function () {
                    global.location.href = buildIndexControlUrl({
                        tab: "submit",
                        url: publicUrl
                    });
                }
                : null;
        }
        if (hint) {
            if (publicUrl) {
                hint.textContent = "URL đã publish: " + publicUrl;
            } else if (articleUrl) {
                hint.textContent = "URL dự kiến — có thể chưa public. Index Control sẽ điền sẵn nếu mở.";
            } else {
                hint.textContent = "Chưa có URL public — mở Index Control để dán URL thủ công.";
            }
        }
    }

    function hideActions() {
        var box = document.getElementById("caIndexControlActions");
        if (box) box.hidden = true;
    }

    global.ContentAiIndexControl = {
        showActions: showActions,
        hideActions: hideActions,
        buildIndexControlUrl: buildIndexControlUrl,
        isHttpUrl: isHttpUrl,
        buildGuessUrl: buildGuessUrl,
        extractDomain: extractDomain
    };
})(window);
