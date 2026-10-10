(function () {
    "use strict";

    const EMAIL_VARS = ["{{name}}", "{{plan}}", "{{expiry_date}}", "{{credit_balance}}"];

    function readToken() {
        try {
            let t = (sessionStorage.getItem("seo_token") || "").trim();
            if (t) return t;
            const m = document.cookie.match(/(?:^|;\s*)seo_token=([^;]*)/);
            if (m) return decodeURIComponent(m[1].replace(/\+/g, " ")).trim();
        } catch (_) {}
        return "";
    }

    function authHeaders(extra) {
        const h = Object.assign({}, extra || {});
        const t = readToken();
        if (t) h.Authorization = "Bearer " + t;
        return h;
    }

    function errMsg(data, status) {
        const d = data && data.detail;
        if (typeof d === "string" && d) return d;
        if (d && typeof d === "object" && d.message) return String(d.message);
        if (Array.isArray(d) && d.length) {
            return d.map(function (e) {
                const loc = Array.isArray(e.loc) ? e.loc.filter(function (x) { return x !== "body"; }).join(".") : "";
                const msg = e.msg || e.message || "invalid";
                return (loc ? loc + ": " : "") + msg;
            }).join("\n");
        }
        if (data && data.message) return String(data.message);
        return "HTTP " + status;
    }

    async function apiGet(path) {
        const res = await fetch(path, { headers: authHeaders() });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(errMsg(data, res.status));
        return data;
    }

    async function apiPost(path, body) {
        const res = await fetch(path, {
            method: "POST",
            headers: authHeaders({ "Content-Type": "application/json" }),
            body: JSON.stringify(body || {}),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(errMsg(data, res.status));
        return data;
    }

    function esc(s) {
        return String(s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
    }

    function fmtDt(iso) {
        if (!iso) return "—";
        try { return new Date(iso).toLocaleString("vi-VN"); } catch (_) { return String(iso); }
    }

    const $ = (id) => document.getElementById(id);

    function toast(msg) {
        const el = $("abToast");
        if (!el) { alert(msg); return; }
        el.hidden = false;
        el.textContent = msg;
        setTimeout(() => { el.hidden = true; }, 2800);
    }

    let recipItems = [];
    let recipLoaded = false;

    function selectedRecipientIds() {
        return Array.from(document.querySelectorAll("#emRecipList input[data-uid]:checked"))
            .map(function (el) { return Number(el.getAttribute("data-uid")); })
            .filter(function (n) { return n > 0; });
    }

    function renderRecipients(items) {
        const box = $("emRecipList");
        const meta = $("emRecipMeta");
        if (!box) return;
        recipItems = items || [];
        recipLoaded = true;
        if (!recipItems.length) {
            box.innerHTML = "<p class=\"ab-muted-text\">Không có email nào trong segment này.</p>";
            if (meta) meta.textContent = "0 email";
            return;
        }
        const q = (($("emRecipSearch") && $("emRecipSearch").value) || "").trim().toLowerCase();
        const filtered = !q ? recipItems : recipItems.filter(function (r) {
            return String(r.email || "").toLowerCase().indexOf(q) >= 0
                || String(r.name || "").toLowerCase().indexOf(q) >= 0
                || String(r.plan_name || "").toLowerCase().indexOf(q) >= 0;
        });
        box.innerHTML = filtered.map(function (r) {
            return "<div class=\"em-recip-row\">"
                + "<input type=\"checkbox\" data-uid=\"" + esc(r.user_id) + "\" checked />"
                + "<label title=\"" + esc(r.email) + "\">" + esc(r.email) + "</label>"
                + "<span class=\"muted\">" + esc(r.plan_name || "") + "</span>"
                + "<span class=\"muted\">" + esc(r.expiry_date || "—") + "</span>"
                + "</div>";
        }).join("");
        if (meta) {
            meta.textContent = filtered.length + " / " + recipItems.length + " email — đã chọn " + selectedRecipientIds().length;
        }
        box.querySelectorAll("input[data-uid]").forEach(function (cb) {
            cb.addEventListener("change", function () {
                if (meta) meta.textContent = filtered.length + " / " + recipItems.length + " email — đã chọn " + selectedRecipientIds().length;
            });
        });
    }

    async function loadSegmentRecipients() {
        const kind = $("emCampSegmentKind")?.value || "active";
        const planId = $("emCampSegmentPlanId")?.value || "";
        const q = ($("emRecipSearch")?.value || "").trim();
        let path = "/admin/api/email/segment-recipients?kind=" + encodeURIComponent(kind) + "&limit=500";
        if (planId) path += "&plan_id=" + encodeURIComponent(planId);
        if (q) path += "&q=" + encodeURIComponent(q);
        const meta = $("emRecipMeta");
        if (meta) meta.textContent = "Đang tải...";
        const data = await apiGet(path);
        renderRecipients(data.items || []);
        return data;
    }

    function visualEl() { return $("emCampHtmlVisual"); }
    function sourceEl() { return $("emCampHtmlBody"); }

    function syncVisualFromSource() {
        const v = visualEl();
        const s = sourceEl();
        if (v && s) v.innerHTML = s.value || "";
    }
    function syncSourceFromVisual() {
        const v = visualEl();
        const s = sourceEl();
        if (v && s) s.value = v.innerHTML || "";
    }

    function campaignHtml() {
        const htmlTab = $("tabHtml");
        if (htmlTab && htmlTab.classList.contains("is-on")) return (sourceEl()?.value || "");
        syncSourceFromVisual();
        return sourceEl()?.value || "";
    }

    function setCampaignHtml(html) {
        if (sourceEl()) sourceEl().value = html || "";
        syncVisualFromSource();
    }

    function insertHtml(html) {
        const v = visualEl();
        v?.focus();
        try {
            document.execCommand("insertHTML", false, html);
        } catch (_) {
            if (v) v.innerHTML += html;
        }
        syncSourceFromVisual();
    }

    async function loadAutomationTemplates() {
        const wrapBody = $("emAutoTplTable") ? $("emAutoTplTable").querySelector("tbody") : null;
        if (!wrapBody) return;
        wrapBody.innerHTML = "";
        const data = await apiGet("/admin/api/email/automation/templates");
        (data.items || []).forEach(function (t) {
            const tr = document.createElement("tr");
            tr.innerHTML =
                "<td>" + esc(t.email_type) + "</td>" +
                "<td>" + (t.enabled ? "ON" : "OFF") + "</td>" +
                "<td>" + esc(t.subject_template || "") + "</td>";
            wrapBody.appendChild(tr);
        });
    }

    async function loadCampaigns() {
        const tb = $("emCampTable") ? $("emCampTable").querySelector("tbody") : null;
        if (!tb) return;
        tb.innerHTML = "";
        const data = await apiGet("/admin/api/email/campaigns");
        (data.items || []).forEach(function (c) {
            const tr = document.createElement("tr");
            const canSend = ["draft", "scheduled", "failed"].indexOf(String(c.status)) >= 0;
            const canCancel = ["draft", "scheduled", "sending"].indexOf(String(c.status)) >= 0;
            tr.innerHTML =
                "<td>" + esc(c.id) + "</td>" +
                "<td>" + esc(c.name) + "</td>" +
                "<td><span class=\"em-status " + esc(c.status) + "\">" + esc(c.status) + "</span></td>" +
                "<td>" +
                (canSend ? "<button type=\"button\" class=\"ab-btn secondary ab-btn-sm\" data-send-id=\"" + esc(c.id) + "\">Gửi ngay</button> " : "") +
                (canCancel ? "<button type=\"button\" class=\"ab-btn secondary ab-btn-sm\" data-cancel-id=\"" + esc(c.id) + "\">Huỷ</button>" : "") +
                "</td>";
            tb.appendChild(tr);
        });
        tb.querySelectorAll("[data-send-id]").forEach(function (btn) {
            btn.addEventListener("click", async function () {
                btn.disabled = true;
                try {
                    await apiPost("/admin/api/email/campaigns/" + encodeURIComponent(btn.getAttribute("data-send-id")) + "/send-now", {});
                    await loadCampaigns();
                    await loadHistory();
                    toast("Đã enqueue gửi campaign.");
                } catch (e) {
                    alert(String(e.message || e));
                } finally {
                    btn.disabled = false;
                }
            });
        });
        tb.querySelectorAll("[data-cancel-id]").forEach(function (btn) {
            btn.addEventListener("click", async function () {
                try {
                    await apiPost("/admin/api/email/campaigns/" + encodeURIComponent(btn.getAttribute("data-cancel-id")) + "/cancel", {});
                    await loadCampaigns();
                } catch (e) {
                    alert(String(e.message || e));
                }
            });
        });
    }

    async function loadHistory() {
        const tb = $("emHistoryTable") ? $("emHistoryTable").querySelector("tbody") : null;
        if (!tb) return;
        tb.innerHTML = "";
        const data = await apiGet("/admin/api/email/history?limit=50&offset=0");
        (data.items || []).forEach(function (r) {
            const tr = document.createElement("tr");
            tr.innerHTML =
                "<td>" + esc(fmtDt(r.created_at)) + "</td>" +
                "<td>" + esc(r.status) + "</td>" +
                "<td>" + esc(r.recipient_email) + "</td>" +
                "<td>" + esc(r.detail || "") + "</td>";
            tb.appendChild(tr);
        });
    }

    async function loadStats() {
        try {
            const s = await apiGet("/admin/api/email/stats");
            if ($("kpiDelivered")) $("kpiDelivered").textContent = s.delivered ?? 0;
            if ($("kpiOpened")) $("kpiOpened").textContent = s.opened ?? 0;
            if ($("kpiClicked")) $("kpiClicked").textContent = s.clicked ?? 0;
            if ($("kpiBounced")) $("kpiBounced").textContent = s.bounced ?? 0;
            if ($("kpiUnsub")) $("kpiUnsub").textContent = s.unsubscribed ?? 0;
        } catch (_) {}
    }

    function aiPayload(action) {
        return {
            action: action,
            goal: $("emAiGoal")?.value || "",
            segment: $("emCampSegmentKind")?.value || "active",
            tone: $("emAiTone")?.value || "professional",
            offer: $("emAiOffer")?.value || $("emCampDiscountCode")?.value || "",
            cta_label: $("emCampCtaLabel")?.value || "Mở ngay",
            cta_url: $("emCampCtaUrl")?.value || "",
            current_subject: $("emCampSubject")?.value || "",
            current_html: campaignHtml(),
        };
    }

    async function runAi(action, btn) {
        const aiBtns = [
            $("btnAiSubject"),
            $("btnAiBody"),
        ].concat(Array.from(document.querySelectorAll("[data-ai]")));
        const active = btn || null;
        const prevLabel = active ? active.textContent : "";
        aiBtns.forEach(function (b) {
            if (!b) return;
            b.disabled = true;
            b.classList.add("is-loading");
        });
        if (active) active.textContent = "⏳ Đang viết...";
        try {
            const data = await apiPost("/admin/api/email/ai/compose", aiPayload(action));
            if (data.subject && $("emCampSubject")) $("emCampSubject").value = data.subject;
            if (data.preheader && $("emCampPreheader")) $("emCampPreheader").value = data.preheader;
            if (data.html_body) setCampaignHtml(data.html_body);
            if (data.text_body && $("emCampTextBody")) $("emCampTextBody").value = data.text_body;
            toast("AI đã soạn xong (metered).");
            return data;
        } finally {
            aiBtns.forEach(function (b) {
                if (!b) return;
                b.disabled = false;
                b.classList.remove("is-loading");
            });
            if (active) active.textContent = prevLabel;
        }
    }

    async function doPreview(mobile) {
        syncSourceFromVisual();
        const data = await apiPost("/admin/api/email/preview", {
            subject: $("emCampSubject").value,
            preheader: $("emCampPreheader").value,
            html_body: campaignHtml(),
            text_body: $("emCampTextBody").value,
            cta_label: $("emCampCtaLabel").value,
            cta_url: $("emCampCtaUrl").value,
        });
        const wrap = $("emPreviewWrap");
        const frame = $("emPreviewFrame");
        wrap.hidden = false;
        wrap.classList.toggle("is-mobile", !!mobile);
        frame.srcdoc = "<!DOCTYPE html><html><head><meta charset='utf-8'><style>body{font-family:Arial,sans-serif;margin:16px;color:#111}</style></head><body>" + (data.html || "") + "</body></html>";
    }

    async function init() {
        const chips = $("emVarChips");
        if (chips) {
            EMAIL_VARS.forEach(function (v) {
                const b = document.createElement("button");
                b.type = "button";
                b.className = "em-chip";
                b.textContent = v;
                b.addEventListener("click", function () { insertHtml(v + " "); });
                chips.appendChild(b);
            });
        }

        document.querySelectorAll("#emToolbar [data-cmd]").forEach(function (btn) {
            btn.addEventListener("click", function () {
                visualEl()?.focus();
                document.execCommand(btn.getAttribute("data-cmd"), false, null);
                syncSourceFromVisual();
            });
        });
        $("tabVisual")?.addEventListener("click", function () {
            $("tabVisual").classList.add("is-on");
            $("tabHtml").classList.remove("is-on");
            syncVisualFromSource();
            $("emVisualWrap").hidden = false;
            sourceEl().hidden = true;
        });
        $("tabHtml")?.addEventListener("click", function () {
            $("tabHtml").classList.add("is-on");
            $("tabVisual").classList.remove("is-on");
            syncSourceFromVisual();
            $("emVisualWrap").hidden = true;
            sourceEl().hidden = false;
        });
        visualEl()?.addEventListener("input", syncSourceFromVisual);
        $("btnInsertLink")?.addEventListener("click", async function () {
            const url = prompt("URL (https://...)");
            if (!url) return;
            try {
                const r = await apiPost("/admin/api/email/validate-url?kind=link&url=" + encodeURIComponent(url), {});
                insertHtml('<a href="' + esc(r.url) + '">' + esc(r.url) + "</a>");
            } catch (e) { alert(String(e.message || e)); }
        });
        $("btnInsertCta")?.addEventListener("click", function () {
            const label = $("emCampCtaLabel").value || "Mở ngay";
            const url = $("emCampCtaUrl").value || "https://seoauto.vn/account-billing";
            insertHtml('<p style="text-align:center;margin:20px 0;"><a href="' + esc(url) + '" style="display:inline-block;padding:12px 20px;background:#16a34a;color:#fff;text-decoration:none;border-radius:8px;font-weight:700;">' + esc(label) + "</a></p>");
        });
        $("btnInsertImgUrl")?.addEventListener("click", async function () {
            const url = prompt("Image URL");
            if (!url) return;
            try {
                const r = await apiPost("/admin/api/email/validate-url?kind=image&url=" + encodeURIComponent(url), {});
                insertHtml('<img src="' + esc(r.url) + '" alt="" style="max-width:100%;" />');
            } catch (e) { alert(String(e.message || e)); }
        });
        $("btnUploadImg")?.addEventListener("click", function () { $("emImgFile")?.click(); });
        $("emImgFile")?.addEventListener("change", async function () {
            const f = $("emImgFile").files && $("emImgFile").files[0];
            if (!f) return;
            const fd = new FormData();
            fd.append("file", f);
            const res = await fetch("/admin/api/email/upload-image", { method: "POST", headers: authHeaders(), body: fd });
            const data = await res.json().catch(() => ({}));
            if (!res.ok) { alert(data.detail || "Upload failed"); return; }
            insertHtml('<img src="' + esc(data.url) + '" alt="" style="max-width:100%;" />');
        });

        $("emCampSendMode")?.addEventListener("change", function () {
            $("emCampScheduledAtWrap").hidden = $("emCampSendMode").value !== "scheduled";
        });

        $("btnRecipReload")?.addEventListener("click", function () {
            loadSegmentRecipients().catch(function (e) { alert(String(e.message || e)); });
        });
        $("btnRecipSelectAll")?.addEventListener("click", function () {
            document.querySelectorAll("#emRecipList input[data-uid]").forEach(function (el) { el.checked = true; });
            renderRecipients(recipItems);
        });
        $("btnRecipClear")?.addEventListener("click", function () {
            document.querySelectorAll("#emRecipList input[data-uid]").forEach(function (el) { el.checked = false; });
            const meta = $("emRecipMeta");
            if (meta) meta.textContent = recipItems.length + " email — đã chọn 0";
        });
        let recipTimer = null;
        $("emCampSegmentKind")?.addEventListener("change", function () {
            loadSegmentRecipients().catch(function (e) { console.error(e); });
        });
        $("emCampSegmentPlanId")?.addEventListener("change", function () {
            if (($("emCampSegmentKind")?.value || "") === "by_plan") {
                loadSegmentRecipients().catch(function (e) { console.error(e); });
            }
        });
        $("emRecipSearch")?.addEventListener("input", function () {
            clearTimeout(recipTimer);
            recipTimer = setTimeout(function () { renderRecipients(recipItems); }, 180);
        });

        // Bind AI / preview first so list API failures never block composer buttons.
        $("btnAiSubject")?.addEventListener("click", function () {
            const btn = $("btnAiSubject");
            runAi("generate", btn).catch(function (e) { alert(String(e.message || e)); });
        });
        $("btnAiBody")?.addEventListener("click", function () {
            const btn = $("btnAiBody");
            runAi("generate", btn).catch(function (e) { alert(String(e.message || e)); });
        });
        document.querySelectorAll("[data-ai]").forEach(function (btn) {
            btn.addEventListener("click", function () {
                runAi(btn.getAttribute("data-ai"), btn).catch(function (e) { alert(String(e.message || e)); });
            });
        });
        $("btnPreviewDesk")?.addEventListener("click", function () { doPreview(false).catch(function (e) { alert(String(e.message || e)); }); });
        $("btnPreviewMob")?.addEventListener("click", function () { doPreview(true).catch(function (e) { alert(String(e.message || e)); }); });

        $("btnSaveAutoTpl")?.addEventListener("click", async function () {
            try {
                await apiPost("/admin/api/email/automation/templates/save", {
                    email_type: $("emAutoEmailType").value,
                    enabled: $("emAutoEnabled").checked,
                    subject_template: $("emAutoSubject").value || "",
                    html_body_template: $("emAutoHtmlBody").value || "",
                    text_body_template: ($("emAutoTextBody").value || "").trim() || null,
                });
                await loadAutomationTemplates();
                toast("Đã lưu template.");
            } catch (e) { alert(String(e.message || e)); }
        });
        $("btnTriggerAutoTick")?.addEventListener("click", async function () {
            const btn = $("btnTriggerAutoTick");
            try {
                btn.disabled = true;
                await apiPost("/admin/api/email/automation/tick", {});
                await loadHistory();
                toast("Đã chạy tick automation.");
            } catch (e) { alert(String(e.message || e)); }
            finally { btn.disabled = false; }
        });

        await Promise.allSettled([
            loadAutomationTemplates().catch(function (e) { console.error(e); }),
            loadCampaigns().catch(function (e) { console.error(e); }),
            loadHistory().catch(function (e) { console.error(e); }),
            loadStats().catch(function (e) { console.error(e); }),
            loadSegmentRecipients().catch(function (e) { console.error(e); }),
        ]);
        $("btnTestSend")?.addEventListener("click", async function () {
            const to = prompt("Gửi test tới email:");
            if (!to) return;
            try {
                await apiPost("/admin/api/email/test-send", {
                    to: to,
                    subject: $("emCampSubject").value,
                    preheader: $("emCampPreheader").value,
                    html_body: campaignHtml(),
                    text_body: $("emCampTextBody").value,
                    cta_label: $("emCampCtaLabel").value,
                    cta_url: $("emCampCtaUrl").value,
                });
                toast("Đã gửi email test.");
            } catch (e) { alert(String(e.message || e)); }
        });

        $("btnCreateCampaign")?.addEventListener("click", async function () {
            syncSourceFromVisual();
            if (!recipLoaded) {
                try { await loadSegmentRecipients(); } catch (_) {}
            }
            const selected = selectedRecipientIds();
            let name = ($("emCampName")?.value || "").trim();
            const subject = ($("emCampSubject")?.value || "").trim();
            const html_body = (campaignHtml() || "").trim();
            let cta_url = ($("emCampCtaUrl")?.value || "").trim();
            if (!cta_url) {
                cta_url = "https://seoauto.vn/account-billing";
                if ($("emCampCtaUrl")) $("emCampCtaUrl").value = cta_url;
            }
            if (!name && subject) {
                name = subject.slice(0, 200);
                if ($("emCampName")) $("emCampName").value = name;
            }
            if (!name) {
                alert("Nhập tên campaign (hoặc subject) trước khi tạo.");
                $("emCampName")?.focus();
                return;
            }
            if (!subject) {
                alert("Nhập Subject email trước khi tạo.");
                $("emCampSubject")?.focus();
                return;
            }
            if (!html_body) {
                alert("Nội dung email (body) đang trống. Viết nội dung hoặc bấm Viết body bằng AI.");
                return;
            }
            const payload = {
                name: name,
                subject: subject,
                preheader: ($("emCampPreheader").value || "").trim() || null,
                html_body: html_body,
                text_body: ($("emCampTextBody").value || "").trim() || null,
                cta_label: ($("emCampCtaLabel").value || "").trim() || "Mở ngay",
                cta_url: cta_url,
                discount_code: ($("emCampDiscountCode").value || "").trim() || null,
                segment_kind: $("emCampSegmentKind").value,
                segment_plan_id: $("emCampSegmentPlanId").value ? Number($("emCampSegmentPlanId").value) : null,
                recipient_user_ids: selected,
                send_mode: $("emCampSendMode").value,
                scheduled_at: null,
                timezone: $("emCampTz").value,
            };
            if (payload.send_mode !== "draft" && selected.length === 0) {
                alert("Chưa chọn Gmail nhận. Đổi Segment (vd. Expired) → tải danh sách → tick email cần gửi.");
                return;
            }
            if (payload.send_mode === "scheduled") {
                const s = ($("emCampScheduledAt").value || "").trim();
                payload.scheduled_at = s ? new Date(s).toISOString() : null;
                if (!payload.scheduled_at) {
                    alert("Chọn thời gian Scheduled at khi gửi theo lịch.");
                    return;
                }
            }
            const btn = $("btnCreateCampaign");
            try {
                btn.disabled = true;
                const res = await apiPost("/admin/api/email/campaigns", payload);
                await loadCampaigns();
                await loadHistory();
                toast("Đã tạo campaign" + (res.recipients_queued != null ? " (" + res.recipients_queued + " email)" : "") + ".");
            } catch (e) {
                alert(String(e.message || e));
            } finally {
                btn.disabled = false;
            }
        });
    }

    document.addEventListener("DOMContentLoaded", init);
})();
