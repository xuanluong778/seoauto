(() => {
    window.__settingsReadSeoToken = function () {
        try {
            let t = (sessionStorage.getItem("seo_token") || "").trim();
            if (!t) {
                const m = document.cookie.match(/(?:^|;\s*)seo_token=([^;]*)/);
                t = m ? decodeURIComponent(m[1].replace(/\+/g, " ")).trim() : "";
                if (t) sessionStorage.setItem("seo_token", t);
            }
            return t;
        } catch (_) {
            const m = document.cookie.match(/(?:^|;\s*)seo_token=([^;]*)/);
            return m ? decodeURIComponent(m[1].replace(/\+/g, " ")).trim() : "";
        }
    };
    window.__settingsAuthHeaders = function (extra) {
        const h = { ...(extra || {}) };
        const t = window.__settingsReadSeoToken();
        if (t) h.Authorization = "Bearer " + t;
        return h;
    };
    window.__settingsAuthJson = function () {
        return window.__settingsAuthHeaders({ "Content-Type": "application/json" });
    };
    window.__settingsFetch = function (url, opts) {
        const o = { credentials: "same-origin", ...(opts || {}) };
        o.headers = window.__settingsAuthHeaders(o.headers || {});
        return fetch(url, o);
    };
    try {
        const path = (window.location && window.location.pathname) ? window.location.pathname.replace(/\/+$/, "") : "";
        document.querySelectorAll(".nav a").forEach((a) => {
            const href = (a.getAttribute("href") || "").trim();
            if (!href || href.startsWith("http")) return;
            const h = href.replace(/\/+$/, "");
            if (h && h === path) a.classList.add("active");
        });
    } catch (_) {}

    const side = document.getElementById("settingsSideNav");
    if (side) {
        const links = Array.from(side.querySelectorAll("a.sb-link"));
        const sections = Array.from(document.querySelectorAll(".settings-main > section"));
        const known = new Set(sections.map((s) => "#" + s.id));
        const sync = () => {
            let hash = (window.location.hash || "#account").split("?")[0] || "#account";
            if (hash === "#api-keys" && !document.getElementById("navApiKeysLink")) {
                window.location.replace("/settings#account");
                return;
            }
            if (hash === "#chatbot-knowledge") {
                window.location.replace("/settings#ai-knowledge-base");
                return;
            }
            if (hash === "#affiliate") {
                window.location.replace("/account-billing?tab=affiliate");
                return;
            }
            if (!known.has(hash)) hash = "#account";
            links.forEach((a) => {
                const on = a.getAttribute("href") === hash;
                a.classList.toggle("sb-active", on);
            });
            sections.forEach((s) => {
                s.classList.toggle("is-active", "#" + s.id === hash);
            });
            if (hash === "#ai-knowledge-base") {
                window.dispatchEvent(new CustomEvent("aikb-tab-show"));
            }
            if (hash === "#publishing") {
                window.dispatchEvent(new CustomEvent("wph-tab-show"));
            }
        };
        links.forEach((a) => a.addEventListener("click", () => { window.requestAnimationFrame(sync); }));
        window.addEventListener("hashchange", sync);
        sync();
    }
})();

/* ====================== API Keys management UI ====================== */
(() => {
    const apiKeysSection = document.getElementById("api-keys");
    const apiKeysNav = document.getElementById("navApiKeysLink");
    if (!apiKeysSection || !apiKeysNav) return;

    const hideApiKeysTab = () => {
        apiKeysNav.hidden = true;
        apiKeysNav.style.display = "none";
        apiKeysSection.hidden = true;
        if ((window.location.hash || "").split("?")[0] === "#api-keys") {
            window.location.replace("/settings#account");
        }
    };

    const applyApiKeysTabByRole = (role) => {
        const r = String(role || "user").toLowerCase();
        if (r === "admin" || r === "super_admin") return true;
        hideApiKeysTab();
        return false;
    };

    (async () => {
        try {
            const r = await __settingsFetch("/auth/me");
            if (!r.ok) {
                hideApiKeysTab();
                return;
            }
            const u = await r.json();
            if (!applyApiKeysTabByRole(u && u.role)) return;
        } catch (_e) {
            hideApiKeysTab();
            return;
        }
    })();

    const PROVIDER_DEFAULT_LIMITS = {
        google_gemini: 1500,
        vertex_ai: 1500,
        openai: 1000,
        openrouter: 1000,
        custom_openai: 1000,
        custom_anthropic: 1000,
        fal_ai: 500,
    };
    const PROVIDER_PLACEHOLDERS = {
        google_gemini: "AIza...",
        vertex_ai: "ya29... or service-account token",
        openai: "sk-...",
        openrouter: "sk-or-...",
        custom_openai: "sk-...",
        custom_anthropic: "sk-ant-...",
        fal_ai: "fal_...",
    };

    const $ = (id) => document.getElementById(id);
    const tbody = $("apikRows");
    const emptyEl = $("apikEmpty");
    const statsRoot = $("apikStats");
    const modal = $("apikModal");
    const modalClose = $("apikModalClose");
    const modalCancel = $("apikCancel");
    const form = $("apikForm");
    const submitBtn = $("apikSubmit");
    const errEl = $("apikModalErr");
    const titleEl = $("apikModalTitle");
    const providersGrid = $("apikProviders");
    const providerInput = $("apikProvider");
    const keyInput = $("apikKey");
    const nameInput = $("apikName");
    const limitInput = $("apikLimit");
    const priorityInput = $("apikPriority");
    const enabledInput = $("apikEnabled");
    const addBtn = $("apikAdd");
    const testBtnModal = $("apikTestModal");

    let editingId = null;

    const fmtInt = (n) => Number(n || 0).toLocaleString("en-US");

    const setStats = (stats) => {
        if (!stats) return;
        statsRoot.querySelectorAll("[data-stat]").forEach((el) => {
            const key = el.getAttribute("data-stat");
            el.textContent = fmtInt(stats[key]);
        });
    };

    const buildRow = (item) => {
        const tr = document.createElement("tr");
        tr.dataset.id = item.id;
        const statusClass = item.enabled ? (item.status === "error" ? "error" : "healthy") : "disabled";
        const statusLabel = item.enabled ? (item.status === "error" ? "Error" : "Healthy") : "Disabled";
        tr.innerHTML = `
            <td>
                <div class="apik-name">${escapeHtml(item.name || "(không tên)")}</div>
                <div class="apik-provider">${escapeHtml(item.provider_label || item.provider || "")}</div>
            </td>
            <td>
                <span class="apik-key-cell">
                    <span class="apik-key-text">${escapeHtml(item.api_key_masked || "")}</span>
                    <button type="button" class="btn-reveal" title="Hiện / ẩn">👁</button>
                </span>
            </td>
            <td>${escapeHtml(String(item.priority || 1))}</td>
            <td>${fmtInt(item.used_today)} / ${item.daily_limit ? fmtInt(item.daily_limit) : "∞"}</td>
            <td><span class="apik-status ${statusClass}">${statusLabel}</span></td>
            <td>
                <label class="apik-toggle">
                    <input type="checkbox" class="apik-toggle-input" ${item.enabled ? "checked" : ""}>
                    <span class="track"></span>
                    <span class="label">${item.enabled ? "On" : "Off"}</span>
                </label>
            </td>
            <td style="text-align: right;">
                <div class="apik-actions">
                    <button type="button" class="btn-test">Test</button>
                    <button type="button" class="btn-edit">Sửa</button>
                    <button type="button" class="btn-del" title="Xóa">×</button>
                </div>
            </td>
        `;

        const revealBtn = tr.querySelector(".btn-reveal");
        const keyText = tr.querySelector(".apik-key-text");
        let revealed = false;
        let fullKey = "";
        revealBtn.addEventListener("click", async () => {
            if (!revealed && !fullKey) {
                try {
                    const r = await __settingsFetch(`/api/settings/api-keys/${item.id}`, {
                        headers: window.__settingsAuthHeaders(),
                    });
                    if (!r.ok) throw new Error("Không tải được khóa");
                    const data = await r.json();
                    fullKey = (data.item && data.item.api_key) || "";
                } catch (e) {
                    alert(e.message || "Không hiện được khóa");
                    return;
                }
            }
            revealed = !revealed;
            keyText.textContent = revealed ? (fullKey || item.api_key_masked || "") : (item.api_key_masked || "");
        });

        const toggleInput = tr.querySelector(".apik-toggle-input");
        toggleInput.addEventListener("change", async () => {
            try {
                const r = await __settingsFetch(`/api/settings/api-keys/${item.id}`, {
                    method: "PATCH",
                    headers: window.__settingsAuthJson(),
                    body: JSON.stringify({ enabled: toggleInput.checked }),
                });
                if (!r.ok) throw new Error("Lỗi cập nhật");
                const data = await r.json();
                setStats(data.stats);
                await refresh();
            } catch (e) {
                alert(e.message || "Không cập nhật được");
                toggleInput.checked = !toggleInput.checked;
            }
        });

        tr.querySelector(".btn-test").addEventListener("click", async () => {
            try {
                const r = await __settingsFetch(`/api/settings/api-keys/${item.id}/test`, {
                    method: "POST",
                    headers: window.__settingsAuthHeaders(),
                });
                const data = await r.json();
                alert(data.message || (data.ok ? "OK" : "Test thất bại"));
            } catch (e) {
                alert(String(e.message || e));
            }
        });

        tr.querySelector(".btn-edit").addEventListener("click", () => openModal(item));

        tr.querySelector(".btn-del").addEventListener("click", async () => {
            if (!confirm(`Xóa khóa "${item.name}"?`)) return;
            try {
                const r = await __settingsFetch(`/api/settings/api-keys/${item.id}`, {
                    method: "DELETE",
                    headers: window.__settingsAuthHeaders(),
                });
                if (!r.ok) throw new Error("Xóa thất bại");
                await refresh();
            } catch (e) {
                alert(String(e.message || e));
            }
        });

        return tr;
    };

    const escapeHtml = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({
        "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    })[c]);

    const DEFAULT_TRIAL_DAYS = 3;

    const renderTrial = (trial) => {
        const t = trial || {};
        const msgEl = $("apikTrialMessage");
        const startEl = $("apikTrialStart");
        const endEl = $("apikTrialEnd");
        const daysEl = $("apikTrialDaysLeft");
        const card = $("apikTrialCard");
        const titleEl = $("apikTrialTitle");
        if (!msgEl) return;
        const trialDays = Number(t.trial_days) > 0 ? Number(t.trial_days) : DEFAULT_TRIAL_DAYS;
        if (titleEl) titleEl.textContent = "Dùng thử " + trialDays + " ngày";
        msgEl.textContent = t.message || "";
        if (t.started_at) {
            try { startEl.textContent = new Date(t.started_at).toLocaleString("vi-VN"); } catch (_) { startEl.textContent = t.started_at; }
        } else {
            startEl.textContent = "—";
        }
        if (t.ends_at) {
            try { endEl.textContent = new Date(t.ends_at).toLocaleString("vi-VN"); } catch (_) { endEl.textContent = t.ends_at; }
        } else {
            endEl.textContent = "—";
        }
        daysEl.textContent = t.is_active ? String(t.days_remaining ?? 0) : "0";
        if (card) {
            card.style.borderColor = t.is_active ? "rgba(34,197,94,.45)" : "rgba(248,113,113,.45)";
            card.style.background = t.is_active ? "rgba(22,101,52,.15)" : "rgba(127,29,29,.2)";
        }
    };

    const refresh = async () => {
        try {
            const r = await __settingsFetch("/api/settings/api-keys", { headers: window.__settingsAuthHeaders() });
            if (!r.ok) throw new Error("Không tải được danh sách");
            const data = await r.json();
            tbody.innerHTML = "";
            (data.items || []).forEach((it) => tbody.appendChild(buildRow(it)));
            emptyEl.hidden = (data.items || []).length > 0;
            setStats(data.stats);
            if (data.trial) renderTrial(data.trial);
        } catch (e) {
            console.error(e);
        }
    };

    const setProvider = (provider) => {
        providerInput.value = provider;
        Array.from(providersGrid.children).forEach((b) => {
            b.classList.toggle("is-selected", b.dataset.provider === provider);
        });
        if (!editingId) {
            const def = PROVIDER_DEFAULT_LIMITS[provider];
            if (def) limitInput.value = String(def);
        }
        keyInput.placeholder = PROVIDER_PLACEHOLDERS[provider] || "API key";
    };

    providersGrid.addEventListener("click", (ev) => {
        const btn = ev.target.closest(".apik-provider-card");
        if (!btn) return;
        setProvider(btn.dataset.provider);
    });

    const openModal = (item) => {
        errEl.textContent = "";
        editingId = item ? item.id : null;
        titleEl.textContent = item ? "Sửa API key" : "Add API key";
        submitBtn.textContent = item ? "Lưu" : "Create";
        nameInput.value = item ? (item.name || "") : "";
        keyInput.value = item ? (item.api_key || "") : "";
        limitInput.value = String(item ? (item.daily_limit || 0) : (PROVIDER_DEFAULT_LIMITS[providerInput.value] || 1500));
        priorityInput.value = String(item ? (item.priority || 1) : 1);
        enabledInput.checked = item ? !!item.enabled : true;
        setProvider(item ? (item.provider || "google_gemini") : "google_gemini");
        modal.classList.add("is-open");
        window.requestAnimationFrame(() => nameInput.focus());
    };

    const closeModal = () => {
        modal.classList.remove("is-open");
        editingId = null;
        errEl.textContent = "";
    };

    addBtn.addEventListener("click", () => openModal(null));
    modalClose.addEventListener("click", closeModal);
    modalCancel.addEventListener("click", closeModal);
    modal.addEventListener("click", (ev) => {
        if (ev.target === modal) closeModal();
    });
    document.addEventListener("keydown", (ev) => {
        if (ev.key === "Escape" && modal.classList.contains("is-open")) closeModal();
    });

    testBtnModal.addEventListener("click", async () => {
        const v = (keyInput.value || "").trim();
        if (!v) {
            errEl.textContent = "Hãy nhập API key trước khi test.";
            return;
        }
        errEl.textContent = "";
        try {
            const r = await __settingsFetch("/api/settings/api-keys/verify", {
                method: "POST",
                headers: window.__settingsAuthJson(),
                body: JSON.stringify({ provider: providerInput.value, api_key: v }),
            });
            const data = await r.json().catch(() => ({}));
            if (data.trial) renderTrial(data.trial);
            const act = data.trial_activation;
            let extra = "";
            if (act && act.activated) extra = "\n\n" + (act.message || "Đã kích hoạt dùng thử.");
            else if (act && act.message) extra = "\n\n" + act.message;
            alert((data.message || (r.ok ? "OK" : "Lỗi")) + extra);
            if (!r.ok) errEl.textContent = typeof data.detail === "string" ? data.detail : (data.message || "Test thất bại");
        } catch (e) {
            errEl.textContent = String(e.message || e);
        }
    });

    form.addEventListener("submit", async (ev) => {
        ev.preventDefault();
        errEl.textContent = "";
        const payload = {
            name: nameInput.value.trim(),
            provider: providerInput.value,
            api_key: keyInput.value.trim(),
            daily_limit: Number(limitInput.value || 0),
            priority: Number(priorityInput.value || 1),
            enabled: enabledInput.checked,
        };
        if (!payload.name) { errEl.textContent = "Cần đặt tên cho khóa."; return; }
        if (!payload.api_key) { errEl.textContent = "Chưa nhập API key."; return; }
        submitBtn.disabled = true;
        try {
            const url = editingId ? `/api/settings/api-keys/${editingId}` : "/api/settings/api-keys";
            const method = editingId ? "PATCH" : "POST";
            const r = await __settingsFetch(url, {
                method,
                headers: window.__settingsAuthJson(),
                body: JSON.stringify(payload),
            });
            const data = await r.json().catch(() => ({}));
            if (!r.ok) {
                const detail = data.detail;
                const msg = typeof detail === "string" ? detail : (data.verify_message || JSON.stringify(detail || data));
                throw new Error(msg || ("HTTP " + r.status));
            }
            if (data.trial) renderTrial(data.trial);
            if (data.trial_activation && data.trial_activation.activated) {
                alert(data.trial_activation.message || "Đã lưu API key.");
            }
            closeModal();
            await refresh();
        } catch (e) {
            errEl.textContent = String(e.message || e);
        } finally {
            submitBtn.disabled = false;
        }
    });

    if (location.hash === "#api-keys") {
        apiKeysSection.scrollIntoView({ behavior: "instant", block: "start" });
    }
    refresh();
})();

/* ====================== Account section ====================== */
(() => {
    const $ = (id) => document.getElementById(id);
    const wrapSigned = $("accSignedIn");
    const wrapAnon = $("accAnon");
    const elAvatar = $("accAvatar");
    const elName = $("accName");
    const elEmail = $("accEmail");
    const elExpires = $("accExpires");
    const elDaysLeft = $("accDaysLeft");
    const elUsageNumber = $("accUsageNumber");
    const elUsageLimit = $("accUsageLimit");
    const elUsagePct = $("accUsagePct");
    const elUsageFill = $("accUsageFill");
    const elLicense = $("accLicense");
    const elPlanBadge = $("accPlanBadge");
    const elLicenseState = $("accLicenseState");
    const btnLogout = $("accLogout");
    const btnVerify = $("accVerify");

    const TOKEN_KEY = "seo_token";
    const token = window.__settingsReadSeoToken ? window.__settingsReadSeoToken() : (sessionStorage.getItem(TOKEN_KEY) || "");

    const showAnon = () => {
        wrapSigned.hidden = true;
        wrapAnon.hidden = false;
    };
    const showSigned = () => {
        wrapSigned.hidden = false;
        wrapAnon.hidden = true;
    };

    const titleFromEmail = (email) => {
        const local = String(email || "").split("@")[0] || "";
        if (!local) return "Người dùng";
        return local
            .replace(/[._-]+/g, " ")
            .split(" ")
            .filter(Boolean)
            .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
            .join(" ");
    };

    const fmtDate = (iso) => {
        try {
            const d = new Date(iso);
            if (Number.isNaN(d.getTime())) return "—";
            const dd = String(d.getDate()).padStart(2, "0");
            const mm = String(d.getMonth() + 1).padStart(2, "0");
            return dd + "/" + mm + "/" + d.getFullYear();
        } catch (_) {
            return "—";
        }
    };

    const daysBetween = (iso) => {
        try {
            const t = new Date(iso).getTime();
            if (Number.isNaN(t)) return null;
            return Math.ceil((t - Date.now()) / (24 * 3600 * 1000));
        } catch (_) {
            return null;
        }
    };

    const buildLicense = (id, email) => {
        const seed = String(id || "") + "|" + String(email || "");
        let h = 0;
        for (let i = 0; i < seed.length; i += 1) {
            h = (h * 31 + seed.charCodeAt(i)) >>> 0;
        }
        return (h.toString(16).padStart(8, "0") + "…");
    };

    const fmtQuotaLimit = (n) => {
        if (n === null || n === undefined) return "—";
        if (Number(n) === -1) return "∞";
        return String(n);
    };
    const fmtQuotaRemain = (n) => {
        if (n === null || n === undefined) return "∞";
        return String(n);
    };

    const renderSaasMe = (data) => {
        const elBadge = document.getElementById("accSaasPlanBadge");
        const elMsg = document.getElementById("accSaasMessage");
        const elStatus = document.getElementById("accSaasStatus");
        const elEnd = document.getElementById("accSaasPeriodEnd");
        const elMonth = document.getElementById("accSaasUsageMonth");
        const elTrialApi = document.getElementById("accSaasTrialApi");
        const tbody = document.getElementById("accSaasQuotaBody");
        if (!elBadge || !tbody) return;

        if (data.plan_name || data.plan_slug) {
            elBadge.textContent = data.plan_name || data.plan_slug;
            elMsg.hidden = true;
        } else {
            elBadge.textContent = "Chưa có gói";
            elMsg.hidden = false;
            elMsg.textContent = data.message || "Bạn chưa có gói SaaS";
            elMsg.className = "acc-saas-msg warn";
        }

        elStatus.textContent = data.subscription_status || "—";
        elEnd.textContent = data.current_period_end ? fmtDate(data.current_period_end) : "—";
        elMonth.textContent = data.usage_month || "—";

        const trialBits = [];
        if (data.ai_access_message) {
            trialBits.push(data.ai_access_message);
        } else if (data.llm_source === "system") {
            trialBits.push("AI: dùng API hệ thống");
        }
        elTrialApi.textContent = trialBits.join(" · ");

        const quotas = data.quotas || [];
        if (!quotas.length) {
            tbody.innerHTML =
                '<tr><td colspan="4" style="color:var(--muted)">Chưa có quota tháng này.</td></tr>';
        } else {
            tbody.innerHTML = "";
            quotas.forEach((row) => {
                const tr = document.createElement("tr");
                tr.innerHTML =
                    "<td>" +
                    String(row.feature_key || "") +
                    "</td><td>" +
                    String(row.quantity_used ?? 0) +
                    "</td><td>" +
                    fmtQuotaLimit(row.limit_value) +
                    "</td><td>" +
                    fmtQuotaRemain(row.quota_remaining) +
                    "</td>";
                tbody.appendChild(tr);
            });
        }
    };

    const loadSaasMe = async () => {
        const tbody = document.getElementById("accSaasQuotaBody");
        if (!token) {
            if (tbody) {
                tbody.innerHTML =
                    '<tr><td colspan="4" style="color:var(--muted)">Đăng nhập để xem gói SaaS.</td></tr>';
            }
            return;
        }
        try {
            const r = await fetch("/api/saas/me", {
                headers: { Authorization: "Bearer " + token },
            });
            if (!r.ok) {
                if (tbody) {
                    tbody.innerHTML =
                        '<tr><td colspan="4" style="color:var(--muted)">Không tải được gói SaaS.</td></tr>';
                }
                return;
            }
            renderSaasMe(await r.json());
        } catch (_) {
            if (tbody) {
                tbody.innerHTML =
                    '<tr><td colspan="4" style="color:var(--muted)">Lỗi tải gói SaaS.</td></tr>';
            }
        }
    };

    const render = (user, stats) => {
        const name = titleFromEmail(user.email);
        elName.textContent = name;
        elEmail.textContent = user.email || "";
        const ch = (name || user.email || "?").trim().charAt(0).toUpperCase();
        elAvatar.textContent = ch || "?";

        const balance = Number(user.credit_balance || 0);
        const limit = Math.max(balance, stats && stats.trial_limit ? Number(stats.trial_limit) : 7);
        const used = Math.max(0, limit - balance);
        elUsageNumber.textContent = String(used);
        elUsageLimit.textContent = String(limit);
        const pct = limit > 0 ? Math.min(100, Math.round((used / limit) * 100)) : 0;
        elUsagePct.textContent = pct + "%";
        elUsageFill.style.width = pct + "%";

        const createdAt = user.created_at;
        const expires = createdAt ? new Date(new Date(createdAt).getTime() + 30 * 24 * 3600 * 1000).toISOString() : null;
        elExpires.textContent = expires ? fmtDate(expires) : "—";
        const left = expires ? daysBetween(expires) : null;
        elDaysLeft.textContent = left == null ? "" : "(" + (left >= 0 ? left + " days left" : "đã hết hạn") + ")";
        elPlanBadge.textContent = balance > 0 ? "Active" : "Dùng thử";

        elLicense.textContent = buildLicense(user.id, user.email);
        elLicenseState.textContent = "License valid";
        elLicenseState.classList.remove("invalid");
    };

    const refresh = async () => {
        if (!token) {
            showAnon();
            return;
        }
        try {
            const liveToken = window.__settingsReadSeoToken ? window.__settingsReadSeoToken() : token;
            const r = await fetch("/auth/me", {
                credentials: "same-origin",
                headers: { Authorization: "Bearer " + liveToken },
            });
            if (!r.ok) {
                showAnon();
                return;
            }
            const user = await r.json();
            showSigned();
            render(user, null);
            await loadSaasMe();
        } catch (_) {
            showAnon();
        }
    };

    btnLogout.addEventListener("click", () => {
        if (typeof window.DigiSeoLogout === "function") {
            window.DigiSeoLogout();
        } else {
            sessionStorage.removeItem(TOKEN_KEY);
            document.cookie = "seo_token=; path=/; max-age=0; SameSite=Lax";
        }
        showAnon();
    });
    btnVerify.addEventListener("click", async () => {
        if (!token) {
            elLicenseState.textContent = "Chưa đăng nhập";
            elLicenseState.classList.add("invalid");
            return;
        }
        try {
            const liveToken = window.__settingsReadSeoToken ? window.__settingsReadSeoToken() : token;
            const r = await fetch("/auth/me", {
                credentials: "same-origin",
                headers: { Authorization: "Bearer " + liveToken },
            });
            if (r.ok) {
                elLicenseState.textContent = "License valid";
                elLicenseState.classList.remove("invalid");
            } else {
                elLicenseState.textContent = "License invalid";
                elLicenseState.classList.add("invalid");
            }
        } catch (_) {
            elLicenseState.textContent = "Không kiểm tra được";
            elLicenseState.classList.add("invalid");
        }
    });

    refresh();
})();

/* ====================== Affiliate section ====================== */
(() => {
    const form = document.getElementById("affForm");
    if (!form) return;
    const fields = ["phone", "bank_name", "account_number", "account_owner"];
    const ids = { phone: "affPhone", bank_name: "affBank", account_number: "affAccNo", account_owner: "affOwner" };
    const LS_KEY = "aff_register_v1";
    const msg = document.getElementById("affMsg");
    const btn = document.getElementById("affSubmit");

    const load = () => {
        try {
            const raw = localStorage.getItem(LS_KEY);
            if (!raw) return;
            const data = JSON.parse(raw);
            fields.forEach((k) => {
                const el = document.getElementById(ids[k]);
                if (el && typeof data[k] === "string") el.value = data[k];
            });
            if (data && data.registered_at) {
                msg.textContent = "Bạn đã đăng ký affiliate. Có thể cập nhật thông tin và lưu lại bất cứ lúc nào.";
                msg.classList.remove("err");
                msg.classList.add("ok");
                btn.textContent = "Cập nhật thông tin";
            }
        } catch (_) {}
    };

    const setMsg = (text, cls) => {
        msg.textContent = text;
        msg.classList.remove("ok", "err");
        if (cls) msg.classList.add(cls);
    };

    form.addEventListener("submit", (e) => {
        e.preventDefault();
        const data = {};
        fields.forEach((k) => {
            data[k] = (document.getElementById(ids[k]).value || "").trim();
        });
        if (!data.phone || !data.bank_name || !data.account_number || !data.account_owner) {
            setMsg("Vui lòng điền đầy đủ thông tin.", "err");
            return;
        }
        if (!/^[0-9+ ()-]{8,20}$/.test(data.phone)) {
            setMsg("Số điện thoại không hợp lệ.", "err");
            return;
        }
        if (!/^[0-9]{6,20}$/.test(data.account_number)) {
            setMsg("Số tài khoản chỉ chứa chữ số (6–20 ký tự).", "err");
            return;
        }
        data.registered_at = new Date().toISOString();
        try {
            localStorage.setItem(LS_KEY, JSON.stringify(data));
        } catch (_) {}
        btn.textContent = "Cập nhật thông tin";
        setMsg("Đăng ký Affiliate thành công! Mã coupon sẽ được gửi qua email khi bộ phận hỗ trợ duyệt.", "ok");
    });

    load();
})();

/* ====================== AI Provider tab ====================== */
(() => {
    const grid = document.getElementById("aipGrid");
    const chk = document.getElementById("aipPipeline");
    const errBox = document.getElementById("aipLoadErr");
    if (!grid || !chk) return;

    const icons = {
        openai: '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M12 4a2 2 0 0 1 2 2v1h2a3 3 0 0 1 3 3v6a3 3 0 0 1-3 3h-1v1a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2v-1H5a3 3 0 0 1-3-3v-6a3 3 0 0 1 3-3h1V6a2 2 0 0 1 2-2h4Z" fill="#00e676"/><circle cx="9" cy="11" r="1.2" fill="#04140a"/><circle cx="15" cy="11" r="1.2" fill="#04140a"/><path d="M9 15h6" stroke="#04140a" stroke-width="1.4" stroke-linecap="round"/></svg>',
        google_gemini: '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" aria-hidden="true"><text x="6" y="17" font-size="14" font-weight="800" fill="#4285f4" font-family="system-ui,sans-serif">G</text></svg>',
        vertex_ai: '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M6 18L12 6l6 12" stroke="#60a5fa" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/><path d="M8.5 14h7" stroke="#60a5fa" stroke-width="2" stroke-linecap="round"/></svg>',
        openrouter: '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M7 7h10M7 17h10M14 7l4 5-4 5M10 17l-4-5 4-5" stroke="#a78bfa" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>',
        custom_openai: '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M8 3h8v6H8V3Z" stroke="#2dd4bf" stroke-width="1.8" stroke-linejoin="round"/><path d="M5 9h14v12H5V9Z" stroke="#2dd4bf" stroke-width="1.8" stroke-linejoin="round"/><path d="M12 13v4" stroke="#2dd4bf" stroke-width="1.8" stroke-linecap="round"/></svg>',
        custom_anthropic: '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" aria-hidden="true"><rect x="4" y="4" width="16" height="6" rx="1" stroke="#fb923c" stroke-width="1.6"/><rect x="4" y="14" width="16" height="6" rx="1" stroke="#fb923c" stroke-width="1.6"/><path d="M8 10v4M16 10v4" stroke="#fb923c" stroke-width="1.6" stroke-linecap="round"/></svg>',
        fallback: '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M12 5v3M5 12H2M22 12h-3M7 7 5.5 5.5M18.5 5.5 17 7M17 17l1.5 1.5M5.5 18.5 7 17" stroke="#facc15" stroke-width="1.8" stroke-linecap="round"/><path d="M16.2 16.2A7 7 0 0 0 8.5 5.8" stroke="#facc15" stroke-width="1.8" stroke-linecap="round"/></svg>',
    };

    const render = (data) => {
        grid.innerHTML = "";
        const active = data.active_provider_id || "";
        (data.cards || []).forEach((c) => {
            const el = document.createElement("article");
            el.className = "aip-card" + (active && c.id === active ? " is-active" : "");
            el.setAttribute("data-provider", c.id);
            const ico = icons[c.id] || icons.openai;
            const st = document.createElement("div");
            st.className = "aip-card-status";
            if (c.status) {
                st.textContent = c.status;
                st.classList.add(c.status_kind === "missing" ? "is-missing" : "is-warn");
            }
            el.innerHTML =
                '<div class="aip-card-top">' +
                '<div class="aip-ico">' +
                ico +
                "</div>" +
                "<div>" +
                '<h4 class="aip-card-title"></h4>' +
                '<p class="aip-card-desc"></p>' +
                "</div>" +
                "</div>";
            el.querySelector(".aip-card-title").textContent = c.title || c.id;
            el.querySelector(".aip-card-desc").textContent = c.description || "";
            el.appendChild(st);
            grid.appendChild(el);
        });
        chk.checked = !!data.pipeline_multi_model;
    };

    const showErr = (t) => {
        if (!errBox) return;
        if (!t) {
            errBox.hidden = true;
            errBox.textContent = "";
            return;
        }
        errBox.hidden = false;
        errBox.textContent = t;
    };

    const load = async () => {
        showErr("");
        try {
            const r = await __settingsFetch("/api/settings/ai-provider", { headers: window.__settingsAuthHeaders() });
            if (!r.ok) {
                showErr("Không tải được cấu hình nhà cung cấp (" + r.status + ").");
                return;
            }
            const data = await r.json();
            render(data);
        } catch (_) {
            showErr("Lỗi mạng khi tải cấu hình nhà cung cấp.");
        }
    };

    chk.addEventListener("change", async () => {
        chk.disabled = true;
        try {
            const r = await __settingsFetch("/api/settings/ai-provider", {
                method: "PATCH",
                headers: window.__settingsAuthJson(),
                body: JSON.stringify({ pipeline_multi_model: chk.checked }),
            });
            if (r.ok) {
                const data = await r.json();
                render(data);
                showErr("");
            } else {
                chk.checked = !chk.checked;
                showErr("Không lưu được Pipeline Multi-Model.");
            }
        } catch (_) {
            chk.checked = !chk.checked;
            showErr("Lỗi mạng khi lưu Pipeline Multi-Model.");
        } finally {
            chk.disabled = false;
        }
    });

    const maybeLoad = () => {
        const h = (window.location.hash || "").split("?")[0];
        if (h === "#ai-provider") load();
    };
    window.addEventListener("hashchange", maybeLoad);
    maybeLoad();
})();

/* ====================== AI Knowledge Base tab (ui v3) ====================== */
(() => {
    const pageEl = document.getElementById("ai-knowledge-base");
    const grid = document.getElementById("aikbGrid");
    const onboardingEl = document.getElementById("aikbOnboarding");
    const listSectionEl = document.getElementById("aikbListSection");
    const heroCreateBtn = document.getElementById("aikbHeroCreate");
    const showGuideBtn = document.getElementById("aikbShowGuide");
    const showListBtn = document.getElementById("aikbShowList");
    const testSearchBtn = document.getElementById("aikbTestSearch");
    const errBox = document.getElementById("aikbLoadErr");
    const modal = document.getElementById("aikbModal");
    if (!pageEl || !grid || !modal) return;

    const form = document.getElementById("aikbForm");
    const addBtn = document.getElementById("aikbAdd");
    const closeBtn = document.getElementById("aikbModalClose");
    const cancelBtn = document.getElementById("aikbCancel");
    const submitBtn = document.getElementById("aikbSubmit");
    const errEl = document.getElementById("aikbModalErr");
    const titleEl = document.getElementById("aikbModalTitle");

    let editingId = null;
    let aikbUserRole = "user";
    let editingKbItem = null;

    const escapeHtml = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({
        "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    })[c]);

    const notifySharedKb = () => {
        const payload = { type: "kb_changed", bot_id: 0, at: Date.now() };
        try {
            const ch = new BroadcastChannel("seoauto_chatbot_kb_v1");
            ch.postMessage(payload);
            ch.close();
        } catch (_e) {}
        try {
            window.dispatchEvent(new CustomEvent("seoauto-kb-changed", { detail: payload }));
        } catch (_e2) {}
    };

    const showLoadErr = (t, kind) => {
        if (!errBox) return;
        if (!t) {
            errBox.hidden = true;
            errBox.textContent = "";
            errBox.classList.remove("is-ok");
            return;
        }
        errBox.hidden = false;
        errBox.textContent = t;
        errBox.classList.toggle("is-ok", kind === "ok");
    };

    const parseKbApiError = async (r, fallback) => {
        const e = await r.json().catch(() => ({}));
        let msg = typeof e.detail === "string" ? e.detail : fallback || ("HTTP " + r.status);
        if (r.status === 401) {
            msg = "Phiên đăng nhập hết hạn. Đăng nhập lại rồi thử.";
        } else if (r.status === 403) {
            msg = msg || "Bạn không có quyền sửa Knowledge Base này.";
        } else if (r.status === 404 && !msg) {
            msg = "Không tìm thấy Knowledge Base hoặc API chưa sẵn sàng. Khởi động lại run.bat.";
        }
        return msg;
    };

    const fetchAikbUserRole = async () => {
        const token = window.__settingsReadSeoToken ? window.__settingsReadSeoToken() : "";
        if (!token) {
            aikbUserRole = "user";
            return;
        }
        try {
            const r = await fetch("/auth/me", {
                credentials: "same-origin",
                headers: { Authorization: "Bearer " + token },
            });
            if (r.ok) {
                const u = await r.json();
                aikbUserRole = String(u.role || "user").toLowerCase();
            }
        } catch (_) {
            aikbUserRole = "user";
        }
    };

    const kbCanEdit = (item) => {
        if (!item) return true;
        if (item.can_edit === false) return false;
        if (item.is_inherited) return false;
        if (item.scope === "global" && aikbUserRole !== "admin") return false;
        return true;
    };

    const kbCanClone = (item) => {
        if (!item) return false;
        if (item.can_clone === true) return true;
        return !!(item.is_inherited || (item.scope === "global" && aikbUserRole !== "admin"));
    };

    const readKbPayload = () => ({
        name: document.getElementById("aikbName").value.trim(),
        brand_name: document.getElementById("aikbBrand").value.trim(),
        website_url: document.getElementById("aikbWebsite").value.trim(),
    });

    const validateKbCreate = (payload) => {
        if (!payload.name) return "Cần đặt tên Knowledge Base.";
        return "";
    };

    let kbItemsCache = [];
    let importKbId = null;
    /** Mặc định luôn là onboarding; reload trang = quay lại hướng dẫn RAG */
    let kbViewMode = "onboarding";

    const syncKbNavActive = () => {
        const searchEl = document.getElementById("aikbSearchModal");
        const searchOpen = searchEl && searchEl.classList.contains("is-open");
        const hasKbs = kbItemsCache.length > 0;
        if (showGuideBtn) showGuideBtn.hidden = false;
        if (showListBtn) showListBtn.hidden = !hasKbs;
        [showGuideBtn, showListBtn, testSearchBtn].forEach((btn) => {
            if (btn) btn.classList.remove("is-active");
        });
        if (searchOpen && testSearchBtn) {
            testSearchBtn.classList.add("is-active");
        } else if (kbViewMode === "list" && showListBtn && hasKbs) {
            showListBtn.classList.add("is-active");
        } else if (showGuideBtn) {
            showGuideBtn.classList.add("is-active");
        }
    };

    const closeSearchModalIfOpen = () => {
        const searchEl = document.getElementById("aikbSearchModal");
        if (searchEl && searchEl.classList.contains("is-open")) {
            searchEl.hidden = true;
            searchEl.classList.remove("is-open");
        }
    };

    const showOnboardingView = () => {
        closeSearchModalIfOpen();
        kbViewMode = "onboarding";
        pageEl.classList.remove("aikb-view-list");
        pageEl.classList.add("aikb-view-onboarding");
        if (onboardingEl) onboardingEl.hidden = false;
        if (listSectionEl) listSectionEl.hidden = true;
        syncKbNavActive();
    };

    const showListView = () => {
        closeSearchModalIfOpen();
        kbViewMode = "list";
        pageEl.classList.remove("aikb-view-onboarding");
        pageEl.classList.add("aikb-view-list");
        if (onboardingEl) onboardingEl.hidden = true;
        if (listSectionEl) listSectionEl.hidden = false;
        syncKbNavActive();
    };

    const updateListBtnLabel = (count) => {
        if (!showListBtn) return;
        showListBtn.textContent = count > 0 ? ("Danh sách KB (" + count + ")") : "Danh sách KB";
    };

    const applyKbView = () => {
        updateListBtnLabel(kbItemsCache.length);
        if (kbViewMode === "list" && kbItemsCache.length > 0) showListView();
        else showOnboardingView();
        syncKbNavActive();
    };

    const fmtNum = (n) => {
        const x = Number(n) || 0;
        if (x >= 1000000) return (x / 1000000).toFixed(1) + "M";
        if (x >= 1000) return (x / 1000).toFixed(1) + "k";
        return String(x);
    };

    const buildCard = (item) => {
        const st = item.stats || {};
        const docs = st.documents || 0;
        const chunks = st.chunks || 0;
        const embDone = st.embeddings_done || 0;
        const embTotal = st.embeddings_total || 0;
        const tokens = st.tokens || 0;
        const embLabel = embTotal ? (embDone + "/" + embTotal) : "0/0";

        const card = document.createElement("article");
        card.className = "aikb-kb-card" + (item.is_default ? " is-default" : "") + (item.enabled ? "" : " is-disabled");
        card.dataset.kbId = item.id;

        card.innerHTML =
            '<div class="aikb-kb-card-head">' +
            '<div class="aikb-kb-card-title-wrap">' +
            '<h3 class="aikb-kb-card-title">' + escapeHtml(item.name) + "</h3>" +
            (item.is_inherited ? '<span class="aikb-badge is-inherited">' + escapeHtml(item.inheritance_label || "Kế thừa từ hệ thống") + "</span>" : "") +
            (item.scope === "global" && aikbUserRole === "admin" ? '<span class="aikb-badge">Global</span>' : "") +
            (item.owner_user_id && aikbUserRole === "admin" ? '<span class="aikb-badge is-owner">User #' + escapeHtml(item.owner_user_id) + "</span>" : "") +
            (item.is_default ? '<span class="aikb-badge">Mặc định</span>' : "") +
            "</div>" +
            '<div class="aikb-kb-card-actions">' +
            (kbCanClone(item) ? '<button type="button" class="aikb-btn-clone btn-clone" title="Sao chép thành bản riêng để chỉnh sửa">Copy bản riêng</button>' : "") +
            '<button type="button" class="aikb-btn-import btn-import"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M12 16V4m0 0 4 4m-4-4 4-4M4 17v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg> Import</button>' +
            '<button type="button" class="aikb-btn-reindex btn-reindex"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M4 12a8 8 0 0 1 13.3-5.7M20 12a8 8 0 0 1-13.3 5.7" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/><path d="M17 6.3V2h4M7 17.7v4h-4" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg> Reindex</button>' +
            '<button type="button" class="aikb-btn-edit-kb btn-edit">Sửa</button>' +
            '<button type="button" class="aikb-btn-del-kb btn-del" title="Xóa KB" aria-label="Xóa KB"><svg width="18" height="18" viewBox="0 0 24 24" fill="none"><path d="M4 7h16M9 7V5a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2m2 0v12a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2V7h12Z" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg></button>' +
            "</div>" +
            "</div>" +
            '<div class="aikb-kb-metrics">' +
            '<div class="aikb-metric aikb-metric-docs' + (docs > 0 ? ' is-clickable' : '') + '" data-action="docs" tabindex="' + (docs > 0 ? '0' : '-1') + '" title="' + (docs > 0 ? 'Xem danh sách tài liệu / sơ đồ tri thức' : '') + '"><span class="aikb-metric-val">' + fmtNum(docs) + '</span><span class="aikb-metric-lbl">Tài liệu</span></div>' +
            '<div class="aikb-metric"><span class="aikb-metric-val">' + fmtNum(chunks) + '</span><span class="aikb-metric-lbl">Chunks</span></div>' +
            '<div class="aikb-metric"><span class="aikb-metric-val">' + embLabel + '</span><span class="aikb-metric-lbl">Embeddings</span></div>' +
            '<div class="aikb-metric"><span class="aikb-metric-val">' + fmtNum(tokens) + '</span><span class="aikb-metric-lbl">Tokens</span></div>' +
            "</div>" +
            (docs > 0 ? "" :
                '<div class="aikb-kb-empty">' +
                '<svg width="40" height="40" viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M8 4h8l2 4H6l2-4Z" stroke="currentColor" stroke-width="1.4"/><path d="M6 8v12h12V8" stroke="currentColor" stroke-width="1.4"/><path d="M10 12h4M10 16h4" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/></svg>' +
                'Chưa có tài liệu nào. Nhấn <strong>Import</strong> để thêm.' +
                "</div>");

        const metricDocs = card.querySelector(".aikb-metric-docs");
        if (metricDocs && docs > 0) {
            const openDocs = () => openDocsModal(item);
            metricDocs.addEventListener("click", (ev) => { ev.stopPropagation(); openDocs(); });
            metricDocs.addEventListener("keydown", (ev) => {
                if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); openDocs(); }
            });
        }

        const canEdit = kbCanEdit(item);
        const btnImport = card.querySelector(".btn-import");
        const btnReindex = card.querySelector(".btn-reindex");
        const btnEdit = card.querySelector(".btn-edit");
        const btnDel = card.querySelector(".btn-del");
        const btnClone = card.querySelector(".btn-clone");
        if (!canEdit) {
            [btnImport, btnReindex, btnEdit, btnDel].forEach((b) => {
                if (b) {
                    b.disabled = true;
                    b.title = item.is_inherited
                        ? "KB kế thừa — chỉ xem. Dùng «Copy bản riêng» để chỉnh sửa."
                        : "KB Global — chỉ admin mới sửa. Xem tài liệu vẫn được.";
                }
            });
        }
        if (btnClone) {
            btnClone.addEventListener("click", async () => {
                const suggested = (item.name || "KB") + " (bản sao)";
                const newName = prompt("Tên Knowledge Base bản sao:", suggested);
                if (newName === null) return;
                try {
                    const r = await __settingsFetch("/api/settings/ai-knowledge-bases/" + encodeURIComponent(item.id) + "/clone", {
                        method: "POST",
                        headers: { ...window.__settingsAuthHeaders(), "Content-Type": "application/json" },
                        body: JSON.stringify({ name: String(newName).trim() || suggested }),
                    });
                    if (!r.ok) throw new Error(await parseKbApiError(r, "Sao chép thất bại"));
                    await refresh();
                    notifySharedKb();
                    showLoadErr("Đã tạo bản sao — bạn có thể sửa KB riêng của mình.", "ok");
                } catch (e) {
                    alert(String(e.message || e));
                }
            });
        }
        btnImport.addEventListener("click", () => {
            if (!kbCanEdit(item)) {
                alert(item.is_inherited
                    ? "KB kế thừa chỉ xem. Nhấn «Copy bản riêng» để tạo bản có thể sửa."
                    : "Knowledge Base toàn cục (Global) chỉ admin mới Import/Reindex/Sửa.");
                return;
            }
            openImportModal(item);
        });
        btnReindex.addEventListener("click", () => {
            if (!kbCanEdit(item)) {
                alert("Knowledge Base toàn cục (Global) chỉ admin mới Import/Reindex/Sửa.");
                return;
            }
            reindexKb(item);
        });
        btnEdit.addEventListener("click", () => openModal(item));
        btnDel.addEventListener("click", async () => {
            if (!kbCanEdit(item)) {
                alert("Knowledge Base toàn cục (Global) chỉ admin mới xóa.");
                return;
            }
            if (!confirm('Xóa knowledge base "' + (item.name || "") + '" và toàn bộ tài liệu?')) return;
            try {
                const r = await __settingsFetch("/api/settings/ai-knowledge-bases/" + encodeURIComponent(item.id), {
                    method: "DELETE",
                    headers: window.__settingsAuthHeaders(),
                });
                if (!r.ok) throw new Error("Xóa thất bại");
                await refresh();
                notifySharedKb();
            } catch (e) {
                alert(String(e.message || e));
            }
        });
        return card;
    };

    const refresh = async () => {
        showLoadErr("");
        await fetchAikbUserRole();
        try {
            const r = await __settingsFetch("/api/settings/ai-knowledge-bases");
            if (!r.ok) {
                if (r.status === 401) {
                    throw new Error(
                        "Phiên đăng nhập hết hạn hoặc chưa đăng nhập. Mở mục Tài khoản → Đăng nhập, hoặc đăng nhập tại trang chủ rồi quay lại."
                    );
                }
                throw new Error("Không tải được danh sách (" + r.status + ")");
            }
            const data = await r.json();
            const items = data.items || [];
            kbItemsCache = items;
            grid.innerHTML = "";
            items.forEach((it) => grid.appendChild(buildCard(it)));
            applyKbView();
        } catch (e) {
            kbViewMode = "onboarding";
            applyKbView();
            showLoadErr(String(e.message || e));
        }
    };

    const openModal = (item) => {
        errEl.textContent = "";
        editingKbItem = item || null;
        editingId = item ? item.id : null;
        const canEdit = !item || kbCanEdit(item);
        titleEl.textContent = item ? "Sửa Knowledge Base" : "Tạo Knowledge Base";
        submitBtn.textContent = item ? "Lưu" : "Tạo KB";
        submitBtn.disabled = !canEdit;
        document.getElementById("aikbName").value = item ? (item.name || "") : "";
        document.getElementById("aikbBrand").value = item ? (item.brand_name || "") : "";
        document.getElementById("aikbWebsite").value = item ? (item.website_url || "") : "";
        document.getElementById("aikbName").disabled = !canEdit;
        document.getElementById("aikbBrand").disabled = !canEdit;
        document.getElementById("aikbWebsite").disabled = !canEdit;
        if (item && !canEdit) {
            errEl.textContent = item.is_inherited
                ? "KB kế thừa từ hệ thống — chỉ xem. Dùng «Copy bản riêng» trên thẻ KB để tạo bản có thể chỉnh sửa."
                : "Đây là Knowledge Base toàn cục (Global). Chỉ tài khoản admin mới sửa tên/thương hiệu. " +
                  "Bạn vẫn xem và tìm kiếm tài liệu bình thường.";
        }
        modal.classList.add("is-open");
    };

    const closeModal = () => {
        modal.classList.remove("is-open");
        editingId = null;
        editingKbItem = null;
        errEl.textContent = "";
        ["aikbName", "aikbBrand", "aikbWebsite"].forEach((id) => {
            const el = document.getElementById(id);
            if (el) el.disabled = false;
        });
        submitBtn.disabled = false;
    };

    addBtn.addEventListener("click", () => openModal(null));
    if (heroCreateBtn) heroCreateBtn.addEventListener("click", () => openModal(null));
    if (showGuideBtn) showGuideBtn.addEventListener("click", showOnboardingView);
    if (showListBtn) showListBtn.addEventListener("click", showListView);
    closeBtn.addEventListener("click", closeModal);
    cancelBtn.addEventListener("click", closeModal);

    form.addEventListener("submit", async (ev) => {
        ev.preventDefault();
        errEl.textContent = "";
        if (editingId && editingKbItem && !kbCanEdit(editingKbItem)) {
            errEl.textContent = "KB Global chỉ admin mới lưu được. Đăng nhập tài khoản admin hoặc chỉ xem tài liệu.";
            return;
        }
        const payload = readKbPayload();
        if (!editingId) {
            const v = validateKbCreate(payload);
            if (v) { errEl.textContent = v; return; }
        } else if (!payload.name) {
            errEl.textContent = "Cần đặt tên Knowledge Base.";
            return;
        }
        submitBtn.disabled = true;
        try {
            const url = editingId
                ? "/api/settings/ai-knowledge-bases/" + encodeURIComponent(editingId)
                : "/api/settings/ai-knowledge-bases";
            const r = await __settingsFetch(url, {
                method: editingId ? "PATCH" : "POST",
                headers: window.__settingsAuthJson(),
                body: JSON.stringify(payload),
            });
            if (!r.ok) {
                throw new Error(await parseKbApiError(r, "Không lưu được Knowledge Base."));
            }
            const wasCreate = !editingId;
            closeModal();
            if (wasCreate) kbViewMode = "list";
            await refresh();
            notifySharedKb();
            if (wasCreate) {
                showLoadErr("Đã tạo Knowledge Base. Bấm Import trên thẻ để thêm tài liệu.", "ok");
                setTimeout(() => showLoadErr(""), 6000);
            }
        } catch (e) {
            errEl.textContent = String(e.message || e);
        } finally {
            submitBtn.disabled = false;
        }
    });


    let docsKbId = null;
    const docsModal = document.getElementById("aikbDocsModal");
    const docsListEl = document.getElementById("aikbDocsList");
    const docsErr = document.getElementById("aikbDocsErr");
    const docsKbName = document.getElementById("aikbDocsKbName");
    const docViewModal = document.getElementById("aikbDocViewModal");
    const docViewTitle = document.getElementById("aikbDocViewTitle");
    const docViewMeta = document.getElementById("aikbDocViewMeta");
    const docViewBody = document.getElementById("aikbDocViewBody");
    const docViewErr = document.getElementById("aikbDocViewErr");

    const closeDocViewModal = () => {
        if (docViewModal) {
            docViewModal.hidden = true;
            docViewModal.classList.remove("is-open");
        }
        if (docsModal && docsKbId) {
            docsModal.hidden = false;
            docsModal.classList.add("is-open");
        }
    };
    const closeDocsModal = () => {
        docsKbId = null;
        if (docsModal) { docsModal.hidden = true; docsModal.classList.remove("is-open"); }
        if (docViewModal) {
            docViewModal.hidden = true;
            docViewModal.classList.remove("is-open");
        }
    };
    const fetchKbDocument = async (kbId, docId) => {
        const id = encodeURIComponent(docId);
        const base = "/api/settings/ai-knowledge-bases/" + encodeURIComponent(kbId) + "/documents";
        let r = await __settingsFetch(base + "/" + id);
        let data = await r.json().catch(() => ({}));
        if (r.ok && data.document) return data.document;
        if (r.status === 404) {
            r = await __settingsFetch(base + "?doc_id=" + id);
            data = await r.json().catch(() => ({}));
            if (r.ok && data.document) return data.document;
        }
        let msg = typeof data.detail === "string" ? data.detail : ("HTTP " + r.status);
        if (r.status === 401 || /not authenticated/i.test(msg)) {
            msg = "Phiên đăng nhập hết hạn. Vui lòng đăng nhập lại tại trang chủ rồi mở lại Cài đặt.";
        }
        throw new Error(msg || "Không tải được tài liệu");
    };
    const renderDocView = (doc) => {
        if (!docViewBody) return;
        const sections = Array.isArray(doc.sections) ? doc.sections : [];
        const isKg = !!doc.is_knowledge_graph;
        if (docViewTitle) docViewTitle.textContent = isKg ? "Sơ đồ tri thức" : (doc.title || "Tài liệu");
        if (docViewMeta) {
            docViewMeta.textContent = (doc.title || doc.filename || "") +
                " · " + (doc.chunk_count || 0) + " chunks · " +
                Number(doc.char_count || 0).toLocaleString("vi-VN") + " ký tự";
        }
        if (sections.length > 1) {
            docViewBody.innerHTML = sections.map((s) =>
                '<section class="aikb-doc-section"><h4>' + escapeHtml(s.title || "") +
                '</h4><pre>' + escapeHtml(s.body || "") + "</pre></section>"
            ).join("");
        } else {
            const body = sections[0] && sections[0].body ? sections[0].body : (doc.content || "");
            docViewBody.innerHTML = "<pre>" + escapeHtml(body) + "</pre>";
        }
    };
    const openDocViewer = async (kbId, docId) => {
        if (!docViewModal || !kbId || !docId) return;
        if (docViewErr) docViewErr.textContent = "";
        if (docViewBody) docViewBody.innerHTML = '<p class="apik-help">Đang tải tài liệu…</p>';
        if (docsModal) {
            docsModal.classList.remove("is-open");
            docsModal.hidden = true;
        }
        docViewModal.hidden = false;
        docViewModal.classList.add("is-open");
        try {
            const doc = await fetchKbDocument(kbId, docId);
            renderDocView(doc || {});
        } catch (e) {
            if (docViewBody) docViewBody.innerHTML = "";
            if (docViewErr) docViewErr.textContent = String(e.message || e);
        }
    };
    const openDocsModal = async (item) => {
        if (!docsModal || !item || !item.id) return;
        docsKbId = item.id;
        if (docsKbName) docsKbName.textContent = "Knowledge Base: " + (item.name || "");
        if (docsErr) docsErr.textContent = "";
        if (docsListEl) docsListEl.innerHTML = '<p class="apik-help">Đang tải…</p>';
        docsModal.hidden = false;
        docsModal.classList.add("is-open");
        try {
            const r = await __settingsFetch(
                "/api/settings/ai-knowledge-bases/" + encodeURIComponent(item.id) + "/documents"
            );
            const data = await r.json().catch(() => ({}));
            if (!r.ok) {
                let msg = typeof data.detail === "string" ? data.detail : ("HTTP " + r.status);
                if (r.status === 401 || /not authenticated/i.test(msg)) {
                    msg = "Phiên đăng nhập hết hạn. Đăng nhập lại tại trang chủ.";
                }
                throw new Error(msg);
            }
            const docs = data.documents || [];
            if (!docsListEl) return;
            if (!docs.length) {
                docsListEl.innerHTML = '<p class="apik-help">Chưa có tài liệu. Bấm Import trên thẻ KB.</p>';
                return;
            }
            docsListEl.innerHTML = "";
            docs.forEach((d) => {
                const btn = document.createElement("button");
                btn.type = "button";
                btn.className = "aikb-doc-row";
                const title = d.title || d.filename || "Tài liệu";
                btn.innerHTML =
                    "<span><strong>" + escapeHtml(title) + '</strong><span class="meta">' +
                    escapeHtml(String(d.chunk_count || 0)) + " chunks · " +
                    escapeHtml(String(d.token_estimate || 0)) + ' tokens</span></span><span aria-hidden="true">→</span>';
                btn.addEventListener("click", () => openDocViewer(item.id, d.id));
                docsListEl.appendChild(btn);
            });
        } catch (e) {
            if (docsListEl) docsListEl.innerHTML = "";
            if (docsErr) docsErr.textContent = String(e.message || e);
        }
    };
    ["aikbDocsClose", "aikbDocsCancel"].forEach((id) => {
        const el = document.getElementById(id);
        if (el) el.addEventListener("click", closeDocsModal);
    });
    ["aikbDocViewClose", "aikbDocViewCancel"].forEach((id) => {
        const el = document.getElementById(id);
        if (el) el.addEventListener("click", closeDocsModal);
    });
    const docViewBack = document.getElementById("aikbDocViewBack");
    if (docViewBack) docViewBack.addEventListener("click", () => { closeDocViewModal(); });
    if (docsModal) docsModal.addEventListener("click", (ev) => { if (ev.target === docsModal) closeDocsModal(); });
    if (docViewModal) docViewModal.addEventListener("click", (ev) => { if (ev.target === docViewModal) closeDocViewModal(); });

    const importModal = document.getElementById("aikbImportModal");
    const importErr = document.getElementById("aikbImportErr");
    const importKbLabel = document.getElementById("aikbImportKbName");
    const fileInput = document.getElementById("aikbFileInput");
    const fileNameEl = document.getElementById("aikbFileName");
    const csvInput = document.getElementById("aikbCsvInput");
    const csvNameEl = document.getElementById("aikbCsvName");
    const pasteTitle = document.getElementById("aikbPasteTitle");
    const pasteText = document.getElementById("aikbPasteText");
    const importSubmit = document.getElementById("aikbImportSubmit");
    const importTabsEl = document.getElementById("aikbImportTabs");
    const searchModal = document.getElementById("aikbSearchModal");
    const searchKb = document.getElementById("aikbSearchKb");
    const searchQuery = document.getElementById("aikbSearchQuery");
    const searchResults = document.getElementById("aikbSearchResults");
    const searchErr = document.getElementById("aikbSearchErr");
    let importPane = "paste";

    const setImportPane = (pane) => {
        importPane = pane === "file" || pane === "csv" ? pane : "paste";
        const scope = importTabsEl || importModal;
        if (scope) {
            scope.querySelectorAll(".aikb-import-tab").forEach((btn) => {
                const on = btn.dataset.pane === importPane;
                btn.classList.toggle("is-active", on);
                btn.setAttribute("aria-selected", on ? "true" : "false");
            });
        }
        const f = document.getElementById("aikbImportPaneFile");
        const p = document.getElementById("aikbImportPanePaste");
        const c = document.getElementById("aikbImportPaneCsv");
        if (f) f.hidden = importPane !== "file";
        if (p) p.hidden = importPane !== "paste";
        if (c) c.hidden = importPane !== "csv";
    };

    if (importTabsEl) {
        importTabsEl.querySelectorAll(".aikb-import-tab").forEach((btn) => {
            btn.addEventListener("click", () => setImportPane(btn.dataset.pane || "paste"));
        });
    }

    const openImportModal = (item) => {
        importKbId = item.id;
        if (importKbLabel) importKbLabel.textContent = "Knowledge Base: " + (item.name || "");
        if (importErr) importErr.textContent = "";
        if (fileInput) fileInput.value = "";
        if (fileNameEl) fileNameEl.textContent = "";
        if (csvInput) csvInput.value = "";
        if (csvNameEl) csvNameEl.textContent = "";
        if (pasteTitle) pasteTitle.value = "";
        if (pasteText) pasteText.value = "";
        setImportPane("paste");
        if (importModal) { importModal.hidden = false; importModal.classList.add("is-open"); }
    };

    const closeImportModal = () => {
        importKbId = null;
        if (importModal) { importModal.hidden = true; importModal.classList.remove("is-open"); }
    };

    if (fileInput) {
        fileInput.addEventListener("change", () => {
            const f = fileInput.files && fileInput.files[0];
            if (fileNameEl) fileNameEl.textContent = f ? ("Đã chọn: " + f.name) : "";
        });
    }
    const fileZone = document.getElementById("aikbFileZone");
    if (fileZone && fileInput) {
        fileZone.addEventListener("click", (ev) => {
            if (ev.target !== fileInput) fileInput.click();
        });
    }
    const csvZone = document.getElementById("aikbCsvZone");
    if (csvInput) {
        csvInput.addEventListener("change", () => {
            const f = csvInput.files && csvInput.files[0];
            if (csvNameEl) csvNameEl.textContent = f ? ("Đã chọn: " + f.name) : "";
        });
    }
    if (csvZone && csvInput) {
        csvZone.addEventListener("click", (ev) => {
            if (ev.target !== csvInput) csvInput.click();
        });
    }

    const runImport = async () => {
        if (!importKbId) return;
        if (importErr) importErr.textContent = "";
        if (importSubmit) importSubmit.disabled = true;
        try {
            let r;
            if (importPane === "paste") {
                const body = { title: (pasteTitle && pasteTitle.value.trim()) || "", text: (pasteText && pasteText.value) || "" };
                if (!body.text.trim()) throw new Error("Cần dán nội dung.");
                r = await __settingsFetch("/api/settings/ai-knowledge-bases/" + encodeURIComponent(importKbId) + "/import-text", {
                    method: "POST",
                    headers: window.__settingsAuthJson(),
                    body: JSON.stringify(body),
                });
            } else {
                const input = importPane === "csv" ? csvInput : fileInput;
                const f = input && input.files && input.files[0];
                if (!f) throw new Error(importPane === "csv" ? "Chọn file CSV để import." : "Chọn file để import.");
                const fd = new FormData();
                fd.append("file", f);
                r = await __settingsFetch("/api/settings/ai-knowledge-bases/" + encodeURIComponent(importKbId) + "/import", {
                    method: "POST",
                    headers: window.__settingsAuthHeaders(),
                    body: fd,
                });
            }
            if (!r.ok) {
                const e = await r.json().catch(() => ({}));
                throw new Error(typeof e.detail === "string" ? e.detail : ("HTTP " + r.status));
            }
            closeImportModal();
            await refresh();
            notifySharedKb();
        } catch (e) {
            if (importErr) importErr.textContent = String(e.message || e);
        } finally {
            if (importSubmit) importSubmit.disabled = false;
        }
    };

    const reindexKb = async (item) => {
        if (!confirm('Reindex toàn bộ tài liệu trong "' + (item.name || "") + '"?')) return;
        try {
            const r = await __settingsFetch("/api/settings/ai-knowledge-bases/" + encodeURIComponent(item.id) + "/reindex", {
                method: "POST",
                headers: window.__settingsAuthHeaders(),
            });
            if (!r.ok) throw new Error("Reindex thất bại");
            await refresh();
            notifySharedKb();
        } catch (e) {
            alert(String(e.message || e));
        }
    };

    const importCloseBtn = document.getElementById("aikbImportClose");
    if (importCloseBtn) importCloseBtn.addEventListener("click", closeImportModal);
    const importCancelBtn = document.getElementById("aikbImportCancel");
    if (importCancelBtn) importCancelBtn.addEventListener("click", closeImportModal);
    if (importSubmit) importSubmit.addEventListener("click", runImport);

    const fillSearchKbs = () => {
        if (!searchKb) return;
        searchKb.innerHTML = "";
        kbItemsCache.forEach((it) => {
            const opt = document.createElement("option");
            opt.value = it.id;
            opt.textContent = it.name;
            searchKb.appendChild(opt);
        });
    };

    const openSearchModal = () => {
        fillSearchKbs();
        if (searchErr) searchErr.textContent = "";
        if (searchResults) searchResults.innerHTML = "";
        if (searchQuery) searchQuery.value = "";
        if (searchModal) { searchModal.hidden = false; searchModal.classList.add("is-open"); }
        syncKbNavActive();
    };
    const closeSearchModal = () => {
        if (searchModal) { searchModal.hidden = true; searchModal.classList.remove("is-open"); }
        syncKbNavActive();
    };

    const runSearch = async () => {
        const kbId = searchKb && searchKb.value;
        const q = searchQuery && searchQuery.value.trim();
        if (!kbId || !q) { if (searchErr) searchErr.textContent = "Chọn KB và nhập truy vấn."; return; }
        if (searchErr) searchErr.textContent = "";
        try {
            const r = await __settingsFetch("/api/settings/ai-knowledge-bases/" + encodeURIComponent(kbId) + "/search", {
                method: "POST",
                headers: window.__settingsAuthJson(),
                body: JSON.stringify({ query: q, limit: 8 }),
            });
            if (!r.ok) throw new Error("Tìm thất bại");
            const data = await r.json();
            const hits = data.hits || [];
            if (!searchResults) return;
            if (!hits.length) {
                searchResults.innerHTML = '<p class="apik-help">Không có kết quả.</p>';
                return;
            }
            searchResults.innerHTML = hits.map((h) =>
                '<article class="aikb-search-hit"><strong>' + escapeHtml(h.document_title || "") +
                " · chunk " + escapeHtml(String(h.chunk_index)) + "</strong><p>" + escapeHtml(h.snippet || "") + "</p></article>"
            ).join("");
        } catch (e) {
            if (searchErr) searchErr.textContent = String(e.message || e);
        }
    };

    if (testSearchBtn) testSearchBtn.addEventListener("click", openSearchModal);
    ["aikbSearchClose", "aikbSearchCancel"].forEach((id) => {
        const el = document.getElementById(id);
        if (el) el.addEventListener("click", closeSearchModal);
    });
    const searchRun = document.getElementById("aikbSearchRun");
    if (searchRun) searchRun.addEventListener("click", runSearch);
    if (searchModal) searchModal.addEventListener("click", (ev) => { if (ev.target === searchModal) closeSearchModal(); });

    const onKbTabShow = () => refresh();
    window.addEventListener("aikb-tab-show", onKbTabShow);
    window.addEventListener("hashchange", () => {
        if ((window.location.hash || "").split("?")[0] === "#ai-knowledge-base") refresh();
    });
    showOnboardingView();
    if ((window.location.hash || "").split("?")[0] === "#ai-knowledge-base") refresh();
    window.addEventListener("digiseo-auth-change", () => {
        if ((window.location.hash || "").split("?")[0] === "#ai-knowledge-base") refresh();
    });
})();

/* ====================== Publishing tab ====================== */
(() => {
    const pubAuthToken = () => (window.__settingsReadSeoToken ? window.__settingsReadSeoToken() : "");
    const pubAuthHeaders = (extra) => window.__settingsAuthHeaders(extra);
    const pubAuthJsonHeaders = () => pubAuthHeaders({ "Content-Type": "application/json" });
    const tabsRoot = document.getElementById("pubTabs");
    const sitesList = document.getElementById("pubSitesList");
    const emptyBox = document.getElementById("pubEmpty");
    const emptyTextEl = document.getElementById("pubEmptyText");
    const msgEl = document.getElementById("pubMsg");
    const titleEl = document.getElementById("pubPanelTitle");
    const leadEl = document.getElementById("pubPanelLead");
    const addBtn = document.getElementById("pubAddBtn");
    const addBtnLabel = document.getElementById("pubAddBtnLabel");
    const haravanGuide = document.getElementById("pubHaravanGuide");
    const warnBox = document.getElementById("pubPluginWarn");
    const warnText = document.getElementById("pubPluginWarnText");
    const featuresBtn = document.getElementById("pubPluginFeaturesBtn");
    const featuresPop = document.getElementById("pubPluginFeaturesPop");
    const featuresClose = document.getElementById("pubPluginFeaturesClose");
    const setFeaturesPopOpen = (open) => {
        if (!featuresPop) return;
        featuresPop.hidden = !open;
        if (featuresBtn) featuresBtn.setAttribute("aria-expanded", open ? "true" : "false");
    };
    if (featuresBtn && featuresPop) {
        featuresBtn.setAttribute("aria-expanded", "false");
        featuresBtn.setAttribute("aria-controls", "pubPluginFeaturesPop");
        featuresBtn.addEventListener("click", () => {
            setFeaturesPopOpen(Boolean(featuresPop.hidden));
        });
    }
    if (featuresClose) {
        featuresClose.addEventListener("click", () => setFeaturesPopOpen(false));
    }
    document.addEventListener("keydown", (ev) => {
        if (ev.key === "Escape" && featuresPop && !featuresPop.hidden) {
            setFeaturesPopOpen(false);
        }
    });
    const modal = document.getElementById("pubModalBackdrop");
    const modalRoot = document.getElementById("pubModalRoot");
    const modalTitleText = document.getElementById("pubModalTitleText");
    const modalTitleIco = document.getElementById("pubModalTitleIco");
    const form = document.getElementById("pubForm");
    const inputName = document.getElementById("pubFormName");
    const inputUrl = document.getElementById("pubFormUrl");
    const inputUser = document.getElementById("pubFormUser");
    const inputPass = document.getElementById("pubFormPass");
    const inputStatus = document.getElementById("pubFormStatus");
    const errBox = document.getElementById("pubFormErr");
    const cancelBtn = document.getElementById("pubFormCancel");
    const pubModalClose = document.getElementById("pubModalClose");
    const submitBtn = document.getElementById("pubFormSubmit");
    const labelName = document.getElementById("pubLabelName");
    const labelUrl = document.getElementById("pubLabelUrl");
    const labelUser = document.getElementById("pubLabelUser");
    const labelPass = document.getElementById("pubLabelPass");
    const passReq = document.getElementById("pubPassReq");
    const passHint = document.getElementById("pubPassHint");
    const wpUserBlock = document.getElementById("pubFormWpUserBlock");
    const wpStatusBlock = document.getElementById("pubFormStatusBlock");
    const pubCategoryBlock = document.getElementById("pubFormCategoryBlock");
    const pubCategorySel = document.getElementById("pubFormCategory");
    const pubLabelCategory = document.getElementById("pubLabelCategory");
    const pubCategoryHint = document.getElementById("pubCategoryHint");
    const hrvIntro = document.getElementById("pubFormHrvIntro");
    const shopifyIntro = document.getElementById("pubFormShopifyBlock");
    const shopifyCreds = document.getElementById("pubFormShopifyCreds");
    const genericPassBlock = document.getElementById("pubFormGenericPassBlock");
    const shopifyClientId = document.getElementById("pubShopifyClientId");
    const shopifyClientSecret = document.getElementById("pubShopifyClientSecret");
    const shopifyApiVersion = document.getElementById("pubShopifyApiVersion");
    const shopifySecretReq = document.getElementById("pubShopifySecretReq");
    const shopifyTipToggle = document.getElementById("pubShopifyTipToggle");
    const hrvTipToggle = document.getElementById("pubHrvTipToggle");
    const toggleShopifyClientId = document.getElementById("pubToggleShopifyClientId");
    const toggleShopifySecret = document.getElementById("pubToggleShopifySecret");
    const webcakeIntro = document.getElementById("pubFormWebcakeBlock");
    const webcakeCreds = document.getElementById("pubFormWebcakeCreds");
    const webcakeAccess = document.getElementById("pubWebcakeAccessToken");
    const webcakeRefresh = document.getElementById("pubWebcakeRefreshToken");
    const webcakeAccessReq = document.getElementById("pubWebcakeAccessReq");
    const webcakeRefreshReq = document.getElementById("pubWebcakeRefreshReq");
    const webcakeTipToggle = document.getElementById("pubWebcakeTipToggle");
    const toggleWebcakeAccess = document.getElementById("pubToggleWebcakeAccess");
    const toggleWebcakeRefresh = document.getElementById("pubToggleWebcakeRefresh");
    const hrvActions = document.getElementById("pubHrvModalActions");
    const hrvTestBtn = document.getElementById("pubHrvTestBtn");
    const hrvSyncBtn = document.getElementById("pubHrvSyncBtn");
    const togglePassBtn = document.getElementById("pubTogglePass");
    if (!tabsRoot || !sitesList) return;
    const byId = (id) => document.getElementById(id);

    const PLATFORM_LABEL = {
        wordpress: "WordPress",
        shopify: "Shopify",
        haravan: "Haravan",
        webcake: "Webcake",
    };
    const CATEGORY_PLATFORMS = ["wordpress", "haravan", "shopify", "webcake"];
    const platformCategoryLabel = (pf) => {
        const key = String(pf || "").toLowerCase();
        const known = PLATFORM_LABEL[key];
        const name = known || (key ? key.charAt(0).toUpperCase() + key.slice(1) : "");
        return name ? ("Danh mục " + name) : "Danh mục";
    };
    const notifyPubCategoriesChanged = (detail) => {
        try {
            window.dispatchEvent(new CustomEvent("seoauto-pub-categories-changed", { detail: detail || {} }));
        } catch (_) {}
        try {
            localStorage.setItem("seoauto_pub_categories_bump", JSON.stringify({ t: Date.now(), ...(detail || {}) }));
        } catch (_) {}
    };
    const fillModalCategorySelect = (items, selectedId) => {
        if (!pubCategorySel) return;
        const cur = String(selectedId || pubCategorySel.value || "").trim();
        pubCategorySel.innerHTML = '<option value="">-- Chọn danh mục --</option>';
        (items || []).forEach((it) => {
            const id = it && it.id != null ? String(it.id) : "";
            const name = it && it.name ? String(it.name) : id;
            if (!id) return;
            const opt = document.createElement("option");
            opt.value = id;
            opt.textContent = name;
            pubCategorySel.appendChild(opt);
        });
        if (cur && ![...pubCategorySel.options].some((o) => o.value === cur)) {
            const opt = document.createElement("option");
            opt.value = cur;
            opt.textContent = "Danh mục #" + cur;
            pubCategorySel.appendChild(opt);
        }
        if (cur && [...pubCategorySel.options].some((o) => o.value === cur)) {
            pubCategorySel.value = cur;
        }
    };
    const setModalCategoryMode = (pf) => {
        const supported = CATEGORY_PLATFORMS.indexOf(pf) >= 0;
        if (pubLabelCategory) pubLabelCategory.textContent = platformCategoryLabel(pf);
        if (pubCategoryBlock) pubCategoryBlock.hidden = !supported;
        if (pubCategorySel) {
            pubCategorySel.disabled = !supported;
            if (!supported) pubCategorySel.innerHTML = '<option value="">-- Chọn danh mục --</option>';
        }
        if (pubCategoryHint && !supported) pubCategoryHint.textContent = "";
    };
    const categoriesPreviewBody = () => {
        const pf = modalPlatform;
        const body = {
            site_id: editingId || "",
            platform: pf,
            url: inputUrl ? inputUrl.value.trim() : "",
            refresh: true,
            selected_id: pubCategorySel ? String(pubCategorySel.value || "") : "",
        };
        if (pf === "wordpress") {
            const b = wordpressPreviewBody();
            body.url = b.url;
            body.username = b.username;
            body.app_password = b.app_password;
        } else if (pf === "haravan") {
            body.private_token = inputPass ? inputPass.value.trim() : "";
            body.app_password = body.private_token;
        } else if (pf === "shopify") {
            const b = shopifyPreviewBody();
            body.store_url = b.store_url;
            body.url = b.store_url;
            body.client_id = b.client_id;
            body.username = b.client_id;
            body.client_secret = b.client_secret;
            body.api_version = b.api_version;
        } else if (pf === "webcake") {
            const b = webcakePreviewBody();
            body.site_url = b.site_url;
            body.url = b.site_url;
            body.access_token = b.access_token;
            body.refresh_token = b.refresh_token;
        }
        return body;
    };
    const loadModalCategories = async (opts) => {
        const refresh = !!(opts && opts.refresh);
        const pf = modalPlatform;
        setModalCategoryMode(pf);
        if (CATEGORY_PLATFORMS.indexOf(pf) < 0) return;
        if (pubCategoryHint) pubCategoryHint.textContent = refresh ? "Đang tải danh mục…" : (pubCategoryHint.textContent || "");
        try {
            let data = {};
            if (editingId && !refresh) {
                const r = await __settingsFetch("/api/settings/publishing-sites/" + encodeURIComponent(editingId) + "/categories");
                data = await r.json().catch(() => ({}));
                if (r.ok && data && data.unsupported) {
                    if (pubCategoryBlock) pubCategoryBlock.hidden = true;
                    if (pubCategorySel) pubCategorySel.disabled = true;
                    if (pubCategoryHint) pubCategoryHint.textContent = "";
                    return;
                }
                if (r.ok && Array.isArray(data.items) && data.items.length) {
                    fillModalCategorySelect(data.items, data.selected_id);
                    if (pubCategoryHint) {
                        pubCategoryHint.textContent = data.message || ("Đã tải " + data.items.length + " danh mục.");
                    }
                    return;
                }
            }
            const r = await __settingsFetch("/api/settings/publishing-sites/categories/preview", {
                method: "POST",
                headers: pubAuthJsonHeaders(),
                body: JSON.stringify(Object.assign({}, categoriesPreviewBody(), { refresh: refresh || !editingId })),
            });
            data = await r.json().catch(() => ({}));
            if (!r.ok) {
                if (pubCategoryHint) pubCategoryHint.textContent = "";
                return;
            }
            if (data && data.unsupported) {
                if (pubCategoryBlock) pubCategoryBlock.hidden = true;
                if (pubCategorySel) pubCategorySel.disabled = true;
                if (pubCategoryHint) pubCategoryHint.textContent = "";
                return;
            }
            const items = Array.isArray(data.items) ? data.items : [];
            fillModalCategorySelect(items, data.selected_id);
            if (pubCategoryHint) {
                pubCategoryHint.textContent = items.length
                    ? (data.message || ("Đã tải " + items.length + " danh mục."))
                    : (data.pending ? "Kiểm tra kết nối để tải danh mục." : "");
            }
            notifyPubCategoriesChanged({ site_id: editingId || "", platform: pf });
        } catch (_) {
            if (pubCategoryHint) pubCategoryHint.textContent = "";
        }
    };
    const PLATFORM_LEAD = {
        wordpress: "Quản lý các website WordPress dùng để xuất bản bài.",
        shopify: "Connect Shopify stores with Client ID & Client Secret from the Dev Dashboard.",
        haravan: "Manage Haravan stores for blog publishing.",
        webcake: "Connect Webcake sites with Access Token and Refresh Token from the admin dashboard.",
    };

    let currentPlatform = "wordpress";
    let cache = { items: {}, counts: {} };
    let editingId = null;
    let modalPlatform = "wordpress";
    const PUB_INPUT_HIST_KEY = "digiseo_pub_input_history_v1";

    const setMsg = (text, kind) => {
        msgEl.textContent = text || "";
        msgEl.classList.remove("ok", "err");
        if (kind) msgEl.classList.add(kind);
    };

    const escapeHtml = (s) => String(s || "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

    const fmtApiDetail = (d) => {
        if (!d) return "";
        if (typeof d === "string") return d;
        if (Array.isArray(d)) {
            return d.map((x) => (x && x.msg) ? x.msg : JSON.stringify(x)).join("; ");
        }
        return String(d);
    };

    const showFormFeedback = (text, kind) => {
        if (!errBox) return;
        errBox.textContent = text || "";
        errBox.classList.remove("ok", "info", "err");
        if (kind === "ok") errBox.classList.add("ok");
        else if (kind === "info") errBox.classList.add("info");
        else if (kind === "err") errBox.classList.add("err");
    };

    const normPubUrl = (raw) => {
        const s = String(raw || "").trim();
        if (!s) return "";
        try {
            const u = new URL(s.includes("://") ? s : `https://${s}`);
            return `${u.protocol}//${u.host}`.replace(/\/+$/, "");
        } catch (_) {
            return s.replace(/\/+$/, "");
        }
    };

    const readPubHist = () => {
        try {
            const raw = localStorage.getItem(PUB_INPUT_HIST_KEY);
            const o = raw ? JSON.parse(raw) : {};
            return o && typeof o === "object" ? o : {};
        } catch (_) {
            return {};
        }
    };

    const writePubHist = (o) => {
        try {
            localStorage.setItem(PUB_INPUT_HIST_KEY, JSON.stringify(o));
        } catch (_) {}
    };

    const platHist = (pf) => {
        const all = readPubHist();
        const k = pf || "wordpress";
        if (!all[k] || typeof all[k] !== "object") {
            all[k] = { names: [], urls: [], users: [], passByUrl: {} };
        }
        if (!Array.isArray(all[k].names)) all[k].names = [];
        if (!Array.isArray(all[k].urls)) all[k].urls = [];
        if (!Array.isArray(all[k].users)) all[k].users = [];
        if (!all[k].passByUrl || typeof all[k].passByUrl !== "object") all[k].passByUrl = {};
        return all[k];
    };

    const pushHistUnique = (arr, val, max) => {
        const v = String(val || "").trim();
        if (!v) return;
        const next = [v, ...arr.filter((x) => String(x).toLowerCase() !== v.toLowerCase())];
        arr.length = 0;
        next.slice(0, max).forEach((x) => arr.push(x));
    };

    const rememberPubFormFields = (pf) => {
        const h = platHist(pf);
        pushHistUnique(h.names, inputName.value, 16);
        const url = normPubUrl(inputUrl.value);
        if (url) pushHistUnique(h.urls, url, 20);
        if (pf === "wordpress") {
            pushHistUnique(h.users, inputUser.value, 12);
            const pass = String(inputPass.value || "").trim().replace(/\s+/g, "");
            if (url && pass) h.passByUrl[url.toLowerCase()] = pass;
        } else {
            const pass = String(inputPass.value || "").trim();
            if (url && pass) h.passByUrl[url.toLowerCase()] = pass;
        }
        const all = readPubHist();
        all[pf || "wordpress"] = h;
        writePubHist(all);
        renderPubDatalists(pf);
    };

    const renderPubDatalists = (pf) => {
        const h = platHist(pf);
        const fill = (el, items) => {
            if (!el) return;
            el.innerHTML = "";
            (items || []).forEach((v) => {
                const opt = document.createElement("option");
                opt.value = v;
                el.appendChild(opt);
            });
        };
        const sites = (cache.items && cache.items[pf]) || [];
        const urlSeen = new Set();
        const urls = [];
        [...h.urls, ...sites.map((s) => s.url)].forEach((raw) => {
            const u = normPubUrl(raw);
            if (!u) return;
            const key = u.toLowerCase();
            if (urlSeen.has(key)) return;
            urlSeen.add(key);
            urls.push(u);
        });
        fill(byId("pubFormNameHistory"), h.names);
        fill(byId("pubFormUrlHistory"), urls.slice(0, 24));
        if (pf === "wordpress") fill(byId("pubFormUserHistory"), h.users);
    };

    const applyPubHistToEmptyFields = (pf) => {
        const h = platHist(pf);
        if (!String(inputName.value || "").trim() && h.names[0]) inputName.value = h.names[0];
        if (!String(inputUrl.value || "").trim() && h.urls[0]) inputUrl.value = h.urls[0];
        if (pf === "wordpress") {
            if (!String(inputUser.value || "").trim() && h.users[0]) inputUser.value = h.users[0];
        }
        fillPassFromUrlHist(pf);
    };

    const fillPassFromUrlHist = (pf) => {
        const url = normPubUrl(inputUrl.value);
        if (!url || String(inputPass.value || "").trim()) return;
        const h = platHist(pf);
        const pass = h.passByUrl[url.toLowerCase()];
        if (pass) inputPass.value = pass;
    };

    const setPanelTitle = () => {
        const label = PLATFORM_LABEL[currentPlatform] || currentPlatform;
        if (titleEl && titleEl.firstChild && titleEl.firstChild.nodeType === Node.TEXT_NODE) {
            titleEl.firstChild.textContent = label + " ";
        } else if (titleEl) {
            const info = titleEl.querySelector(".info");
            titleEl.textContent = label + " ";
            if (info) titleEl.appendChild(info);
        }
    };

    const PUB_SUPPORTED = ["wordpress", "haravan", "shopify", "webcake"];

    const applyModalMode = (pf, mode) => {
        const isHrv = pf === "haravan";
        const isShopify = pf === "shopify";
        const isWebcake = pf === "webcake";
        const isWp = pf === "wordpress";
        const isToken = isHrv || isShopify || isWebcake;
        modalPlatform = pf;
        if (modalRoot) {
            modalRoot.classList.toggle("is-haravan", isHrv);
            modalRoot.classList.toggle("is-shopify", isShopify);
            modalRoot.classList.toggle("is-webcake", isWebcake);
        }
        if (modalTitleIco) {
            if (isHrv) {
                modalTitleIco.hidden = false;
                modalTitleIco.textContent = "ⓘ";
            } else if (isShopify) {
                modalTitleIco.hidden = false;
                modalTitleIco.textContent = "S";
            } else if (isWebcake) {
                modalTitleIco.hidden = false;
                modalTitleIco.textContent = "W";
            } else {
                modalTitleIco.hidden = true;
            }
        }
        if (hrvIntro) hrvIntro.hidden = !isHrv;
        if (shopifyIntro) shopifyIntro.hidden = !isShopify;
        if (webcakeIntro) webcakeIntro.hidden = !isWebcake;
        if (shopifyCreds) shopifyCreds.hidden = !isShopify;
        if (webcakeCreds) webcakeCreds.hidden = !isWebcake;
        if (genericPassBlock) genericPassBlock.hidden = isShopify || isWebcake;
        const showConnActions = isWp || isHrv || isShopify || isWebcake;
        if (hrvActions) {
            hrvActions.classList.toggle("is-hidden", !showConnActions);
            if (showConnActions) hrvActions.removeAttribute("hidden");
            else hrvActions.setAttribute("hidden", "");
        }
        const setConnBtnLabel = (btn, text) => {
            if (!btn) return;
            const lab = btn.querySelector(".pub-conn-btn-label");
            if (lab) lab.textContent = text;
        };
        if (showConnActions) {
            if (isHrv || isShopify) {
                setConnBtnLabel(hrvTestBtn, "Test connection");
                setConnBtnLabel(hrvSyncBtn, "Sync Blogs");
            } else if (isWebcake) {
                setConnBtnLabel(hrvTestBtn, "Check connection");
                setConnBtnLabel(hrvSyncBtn, "Sync categories");
            } else {
                setConnBtnLabel(hrvTestBtn, "Kiểm tra kết nối");
                setConnBtnLabel(hrvSyncBtn, "Đồng bộ bài viết");
            }
        }
        if (wpUserBlock) wpUserBlock.hidden = !isWp;
        if (wpStatusBlock) wpStatusBlock.hidden = !isWp;
        if (shopifySecretReq) shopifySecretReq.style.display = isShopify && mode === "edit" ? "none" : "";
        if (webcakeAccessReq) webcakeAccessReq.style.display = isWebcake && mode === "edit" ? "none" : "";
        if (webcakeRefreshReq) webcakeRefreshReq.style.display = isWebcake && mode === "edit" ? "none" : "";
        if (passHint) {
            if (isHrv) {
                passHint.hidden = false;
                passHint.textContent = "Get from partners.haravan.com → Apps → your app → Private Token";
            } else if (isShopify || isWebcake) {
                passHint.hidden = true;
                passHint.textContent = "";
            } else {
                passHint.hidden = true;
                passHint.textContent = "";
            }
        }
        if (inputUser) {
            if (isWp) inputUser.setAttribute("required", "required");
            else inputUser.removeAttribute("required");
        }
        if (isHrv) {
            if (labelName) labelName.innerHTML = 'Display name <span class="req">*</span>';
            if (labelUrl) labelUrl.innerHTML = 'Store URL <span class="req">*</span>';
            inputUrl.placeholder = "mystore.myharavan.com";
            if (labelPass) labelPass.innerHTML = 'Private Token <span class="req">*</span>';
            inputPass.placeholder = "Private Token from Haravan Partners";
            inputName.placeholder = "e.g. My Haravan Store";
        } else if (isShopify) {
            if (labelName) labelName.innerHTML = 'Display name <span class="req">*</span>';
            if (labelUrl) labelUrl.innerHTML = 'Store URL <span class="req">*</span>';
            inputUrl.placeholder = "mystore.myshopify.com";
            inputName.placeholder = "e.g. My Shopify Store";
            if (shopifyClientSecret) {
                shopifyClientSecret.placeholder = mode === "edit"
                    ? "Leave blank to keep current secret"
                    : "Client Secret from Shopify Dev Dashboard";
            }
        } else if (isWebcake) {
            if (labelName) labelName.innerHTML = 'Display name <span class="req">*</span>';
            if (labelUrl) labelUrl.innerHTML = 'Site URL <span class="req">*</span>';
            inputUrl.placeholder = "https://mysite.webcake.io";
            inputName.placeholder = "E.g. My Webcake Site";
            if (webcakeAccess) {
                webcakeAccess.placeholder = mode === "edit"
                    ? "Leave blank to keep current token"
                    : "Access Token from Webcake";
            }
            if (webcakeRefresh) {
                webcakeRefresh.placeholder = mode === "edit"
                    ? "Leave blank to keep current token"
                    : "Refresh Token from Webcake";
            }
        } else {
            if (labelName) labelName.innerHTML = 'Tên gợi nhớ <span class="req">*</span>';
            if (labelUrl) labelUrl.innerHTML = 'Website URL <span class="req">*</span>';
            inputUrl.placeholder = "https://your-site.com";
            if (labelPass) labelPass.innerHTML = 'Application Password <span class="req">*</span>';
            inputPass.placeholder = "Tạo trong WP → Users → Profile → Application Passwords";
            inputName.placeholder = "Ví dụ: itsieuviet";
        }
        if (passReq) passReq.style.display = isToken && mode === "edit" ? "none" : "";
        if (cancelBtn) cancelBtn.textContent = isHrv || isShopify || isWebcake ? "Cancel" : "Hủy";
        if (submitBtn) {
            if (isHrv) submitBtn.textContent = mode === "edit" ? "Save" : "Add new";
            else if (isShopify || isWebcake) submitBtn.textContent = mode === "edit" ? "Save" : "Add new";
            else submitBtn.textContent = mode === "edit" ? "Cập nhật" : "Lưu";
        }
        if (modalTitleText) {
            if (isHrv) {
                modalTitleText.textContent = mode === "edit" ? "Edit Haravan Store" : "Add Haravan Store";
            } else if (isShopify) {
                modalTitleText.textContent = mode === "edit" ? "Edit Shopify Store" : "Add Shopify Store";
            } else if (isWebcake) {
                modalTitleText.textContent = mode === "edit" ? "Edit Webcake config" : "Add Webcake config";
            } else {
                modalTitleText.textContent = mode === "edit" ? "Sửa site WordPress" : "Thêm site WordPress";
            }
        }
        if (inputPass.type !== "password") {
            inputPass.type = "password";
        }
        setModalCategoryMode(pf);
    };

    const showModal = (mode, site) => {
        const pf = (site && site.platform) || currentPlatform;
        if (!PUB_SUPPORTED.includes(pf)) return;
        editingId = (mode === "edit" && site) ? site.id : null;
        applyModalMode(pf, editingId ? "edit" : "create");
        showFormFeedback("", "");
        inputName.value = site && site.name ? site.name : "";
        inputUrl.value = site && site.url ? site.url : "";
        inputUser.value = site && site.username ? site.username : "";
        inputPass.value = "";
        if (shopifyClientId) shopifyClientId.value = (site && site.username) ? site.username : "";
        if (shopifyClientSecret) shopifyClientSecret.value = "";
        if (shopifyApiVersion) {
            const ver = (site && site.shopify_api_version) ? site.shopify_api_version : "2025-01";
            shopifyApiVersion.value = ver;
        }
        if (webcakeAccess) webcakeAccess.value = "";
        if (webcakeRefresh) webcakeRefresh.value = "";
        if (pf === "haravan") {
            inputPass.placeholder = "Private Token from Haravan Partners";
        } else if (pf === "shopify") {
            inputPass.placeholder = "";
        } else if (pf === "webcake") {
            inputPass.placeholder = "";
        } else {
            inputPass.placeholder = editingId
                ? "Để trống nếu không đổi mật khẩu"
                : "Tạo trong WP → Users → Profile → Application Passwords";
        }
        inputStatus.value = (site && site.default_status) || "draft";
        fillModalCategorySelect([], "");
        if (pubCategoryHint) pubCategoryHint.textContent = editingId ? "" : "Tự tải sau khi kết nối thành công.";
        renderPubDatalists(pf);
        if (!editingId) applyPubHistToEmptyFields(pf);
        modal.classList.add("is-open");
        [hrvTipToggle, shopifyTipToggle, webcakeTipToggle].forEach((btn) => {
            if (btn) btn.setAttribute("aria-expanded", "false");
        });
        setTimeout(() => inputName.focus(), 30);
        if (editingId) void loadModalCategories({ refresh: false });
    };

    const hideModal = () => {
        modal.classList.remove("is-open");
        editingId = null;
        if (modalRoot) {
            modalRoot.classList.remove("is-haravan");
            modalRoot.classList.remove("is-shopify");
            modalRoot.classList.remove("is-webcake");
        }
    };

    const packWebcakeSecrets = (accessToken, refreshToken) =>
        JSON.stringify({
            v: 1,
            access_token: String(accessToken || ""),
            refresh_token: String(refreshToken || ""),
            expires_at: "",
        });

    const webcakePreviewBody = () => ({
        site_url: inputUrl.value.trim(),
        access_token: webcakeAccess ? webcakeAccess.value.trim() : "",
        refresh_token: webcakeRefresh ? webcakeRefresh.value.trim() : "",
    });

    const packShopifySecrets = (clientSecret, apiVersion) =>
        JSON.stringify({
            v: 1,
            client_secret: String(clientSecret || ""),
            api_version: String(apiVersion || "2025-01"),
            access_token: "",
            expires_at: "",
        });

    const shopifyPreviewBody = () => ({
        store_url: inputUrl.value.trim(),
        client_id: shopifyClientId ? shopifyClientId.value.trim() : "",
        client_secret: shopifyClientSecret ? shopifyClientSecret.value.trim() : "",
        api_version: shopifyApiVersion ? shopifyApiVersion.value : "2025-01",
    });

    if (pubCategorySel) {
        pubCategorySel.addEventListener("change", () => {
            const selectedId = String(pubCategorySel.value || "");
            if (editingId) {
                void __settingsFetch("/api/settings/publishing-sites/" + encodeURIComponent(editingId) + "/categories", {
                    method: "POST",
                    headers: pubAuthJsonHeaders(),
                    body: JSON.stringify({ refresh: false, selected_id: selectedId }),
                }).then(() => notifyPubCategoriesChanged({ site_id: editingId, platform: modalPlatform })).catch(() => {});
                return;
            }
            void __settingsFetch("/api/settings/publishing-sites/categories/preview", {
                method: "POST",
                headers: pubAuthJsonHeaders(),
                body: JSON.stringify(Object.assign({}, categoriesPreviewBody(), { refresh: false, selected_id: selectedId })),
            }).catch(() => {});
        });
    }

    const renderTabs = () => {
        tabsRoot.querySelectorAll(".pub-tab").forEach((btn) => {
            const p = btn.getAttribute("data-platform");
            btn.classList.toggle("is-active", p === currentPlatform);
            const badge = btn.querySelector(".pub-tab-badge");
            const c = (cache.counts && cache.counts[p]) || 0;
            if (badge) {
                badge.textContent = String(c);
                badge.setAttribute("data-count", String(c));
            }
        });
        setPanelTitle();
        leadEl.textContent = PLATFORM_LEAD[currentPlatform] || "";
        if (haravanGuide) haravanGuide.hidden = currentPlatform !== "haravan";
        if (warnBox) warnBox.hidden = currentPlatform !== "wordpress";
        const supported = PUB_SUPPORTED.includes(currentPlatform);
        addBtn.disabled = !supported;
        addBtn.style.opacity = supported ? "1" : "0.5";
        addBtn.style.cursor = supported ? "pointer" : "not-allowed";
        if (addBtnLabel) {
            if (currentPlatform === "haravan" || currentPlatform === "shopify") {
                addBtnLabel.textContent = "Add store";
            } else if (currentPlatform === "webcake") {
                addBtnLabel.textContent = "Add config";
            } else {
                addBtnLabel.textContent = "Add Site";
            }
        }
        if (emptyTextEl) {
            if (currentPlatform === "haravan") {
                emptyTextEl.innerHTML = 'No store yet — click <strong>Add store</strong> to connect your first Haravan store.';
            } else if (currentPlatform === "shopify") {
                emptyTextEl.innerHTML = 'Chưa có store — bấm <strong>Add store</strong> để thêm Shopify.';
            } else if (currentPlatform === "webcake") {
                emptyTextEl.innerHTML = 'No config yet — click <strong>Add config</strong> to connect your first Webcake site.';
            } else if (currentPlatform === "wordpress") {
                emptyTextEl.innerHTML = 'Chưa có site nào — bấm <strong>Add Site</strong> để kết nối website đầu tiên.';
            } else {
                emptyTextEl.innerHTML = 'Chưa có kết nối nào cho nền tảng này.';
            }
        }
    };

    const buildBadge = (site) => {
        if (site.verified) {
            return '<span class="pub-badge ok">✓ Verified</span>';
        }
        return '<span class="pub-badge muted">Chưa kiểm tra</span>';
    };

    const buildPluginBadge = (site) => {
        if (site.platform !== "wordpress") return "";
        if (!site.verified) return "";
        if (site.plugin_installed) {
            return '<span class="pub-badge ok">Plugin OK</span>';
        }
        return '<span class="pub-badge warn">⚠ Chưa cài SEO Helper</span>';
    };

    const buildCard = (site) => {
        const card = document.createElement("article");
        card.className = "pub-site-card";
        card.setAttribute("data-id", site.id);
        const fav = site.favicon_url || "";
        const initial = (site.name || site.url || "?").trim().charAt(0).toUpperCase();
        const fmtTime = (iso) => {
            if (!iso) return "";
            try {
                const d = new Date(iso);
                if (Number.isNaN(d.getTime())) return "";
                return d.toLocaleString("vi-VN");
            } catch (_) { return ""; }
        };
        const isHrv = site.platform === "haravan";
        const userRow = !isHrv && site.username
            ? "<span>User: <strong></strong></span>"
            : "";
        const lastMsgRow = isHrv && site.last_message
            ? '<div class="pub-site-hint" style="color:#94a3b8;font-size:0.82rem;margin-top:6px;line-height:1.45">' + escapeHtml(site.last_message) + "</div>"
            : "";
        const verifyTitle = isHrv ? "Test connection" : "Kiểm tra lại";
        card.innerHTML =
            (fav
                ? '<img class="pub-site-favicon" src="' + escapeHtml(fav) + '" alt="" onerror="this.replaceWith(Object.assign(document.createElement(\'div\'),{className:\'pub-site-favicon\',textContent:\'' + initial + '\'}))" />'
                : '<div class="pub-site-favicon">' + initial + "</div>") +
            '<div class="pub-site-body">' +
            '<div class="pub-site-name-row">' +
            '<span class="pub-site-name"></span>' +
            buildBadge(site) +
            buildPluginBadge(site) +
            "</div>" +
            '<a class="pub-site-url" href="' + escapeHtml(site.url) + '" target="_blank" rel="noopener">' + escapeHtml(site.url) + "</a>" +
            '<div class="pub-site-meta">' +
            userRow +
            "<span>Status: <strong>" + escapeHtml(site.default_status || "draft") + "</strong></span>" +
            (site.last_checked_at ? "<span>Kiểm tra: " + escapeHtml(fmtTime(site.last_checked_at)) + "</span>" : "") +
            "</div>" +
            lastMsgRow +
            "</div>" +
            '<div class="pub-site-actions">' +
            '<button type="button" class="pub-action-btn refresh" data-act="verify" title="' + escapeHtml(verifyTitle) + '">' +
            '<svg width="18" height="18" viewBox="0 0 24 24" fill="none"><path d="M4 12a8 8 0 0 1 14-5.3M20 12a8 8 0 0 1-14 5.3M18 4v4h-4M6 20v-4h4" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>' +
            "</button>" +
            '<button type="button" class="pub-action-btn" data-act="edit">Sửa</button>' +
            '<button type="button" class="pub-action-btn danger" data-act="delete">Xóa</button>' +
            "</div>";
        card.querySelector(".pub-site-name").textContent = site.name || "(chưa đặt tên)";
        const firstStrong = card.querySelector(".pub-site-meta strong");
        if (firstStrong && site.username && !isHrv) firstStrong.textContent = site.username;
        return card;
    };

    const render = () => {
        renderTabs();
        const items = (cache.items && cache.items[currentPlatform]) || [];
        sitesList.innerHTML = "";
        emptyBox.hidden = items.length > 0;
        items.forEach((site) => sitesList.appendChild(buildCard(site)));
        if (currentPlatform === "wordpress") {
            const missing = items.filter((s) => s.verified && !s.plugin_installed);
            if (missing.length > 0) {
                warnBox.hidden = false;
                const names = missing.map((m) => '"' + (m.name || m.url) + '"').join(", ");
                warnText.innerHTML = "Site " + escapeHtml(names) + " chưa cài plugin <strong>Seoauto SEO Helper</strong>. Plugin sẽ tự tối ưu SEO (OpenGraph, Schema, RankMath/Yoast sync) cho bài đăng từ Seoauto.";
            } else {
                warnBox.hidden = true;
            }
        } else {
            warnBox.hidden = true;
        }
    };

    const fetchSites = async () => {
        try {
            const r = await __settingsFetch("/api/settings/publishing-sites", { headers: pubAuthHeaders() });
            if (!r.ok) {
                setMsg("Không tải được danh sách site (" + r.status + ").", "err");
                return;
            }
            const data = await r.json();
            cache = { items: data.items || {}, counts: data.counts || {} };
            render();
            renderPubDatalists(currentPlatform);
            setMsg("");
        } catch (_) {
            setMsg("Lỗi mạng khi tải danh sách site.", "err");
        }
    };

    tabsRoot.addEventListener("click", (e) => {
        const btn = e.target.closest(".pub-tab");
        if (!btn) return;
        currentPlatform = btn.getAttribute("data-platform") || "wordpress";
        render();
    });

    addBtn.addEventListener("click", () => {
        if (!PUB_SUPPORTED.includes(currentPlatform)) {
            setMsg("Nền tảng này chưa hỗ trợ thêm site.", "err");
            return;
        }
        showModal("create", null);
    });
    if (pubModalClose) {
        pubModalClose.addEventListener("click", (e) => {
            e.preventDefault();
            e.stopPropagation();
            hideModal();
        });
    }
    if (cancelBtn) {
        cancelBtn.addEventListener("click", (e) => {
            e.preventDefault();
            hideModal();
        });
    }
    // Không đóng khi click ra ngoài backdrop — chỉ đóng bằng × hoặc Hủy.

    if (togglePassBtn && inputPass) {
        togglePassBtn.addEventListener("click", () => {
            inputPass.type = inputPass.type === "password" ? "text" : "password";
        });
    }
    if (toggleShopifySecret && shopifyClientSecret) {
        toggleShopifySecret.addEventListener("click", () => {
            shopifyClientSecret.type = shopifyClientSecret.type === "password" ? "text" : "password";
        });
    }
    if (toggleShopifyClientId && shopifyClientId) {
        toggleShopifyClientId.addEventListener("click", () => {
            shopifyClientId.type = shopifyClientId.type === "password" ? "text" : "password";
        });
    }
    if (shopifyTipToggle) {
        shopifyTipToggle.addEventListener("click", () => {
            const open = shopifyTipToggle.getAttribute("aria-expanded") !== "false";
            shopifyTipToggle.setAttribute("aria-expanded", open ? "false" : "true");
        });
    }
    if (hrvTipToggle) {
        hrvTipToggle.addEventListener("click", () => {
            const open = hrvTipToggle.getAttribute("aria-expanded") !== "false";
            hrvTipToggle.setAttribute("aria-expanded", open ? "false" : "true");
        });
    }
    if (toggleWebcakeAccess && webcakeAccess) {
        toggleWebcakeAccess.addEventListener("click", () => {
            webcakeAccess.type = webcakeAccess.type === "password" ? "text" : "password";
        });
    }
    if (toggleWebcakeRefresh && webcakeRefresh) {
        toggleWebcakeRefresh.addEventListener("click", () => {
            webcakeRefresh.type = webcakeRefresh.type === "password" ? "text" : "password";
        });
    }
    if (webcakeTipToggle) {
        webcakeTipToggle.addEventListener("click", () => {
            const open = webcakeTipToggle.getAttribute("aria-expanded") !== "false";
            webcakeTipToggle.setAttribute("aria-expanded", open ? "false" : "true");
        });
    }

    const haravanPreviewBody = () => ({
        store_url: inputUrl.value.trim(),
        private_token: inputPass.value.trim(),
    });

    const wordpressPreviewBody = () => ({
        url: normPubUrl(inputUrl.value),
        username: inputUser.value.trim(),
        app_password: String(inputPass.value || "").trim().replace(/\s+/g, ""),
    });

    if (hrvTestBtn) {
        hrvTestBtn.addEventListener("click", async (e) => {
            e.preventDefault();
            e.stopPropagation();
            const pf = modalPlatform;
            const testLabel = hrvTestBtn.querySelector(".pub-conn-btn-label");
            const oldLabel = testLabel ? testLabel.textContent : "";
            hrvTestBtn.disabled = true;
            const isEnConn = pf === "haravan" || pf === "shopify" || pf === "webcake";
            if (testLabel) {
                testLabel.textContent = isEnConn ? (pf === "webcake" ? "Checking…" : "Testing…") : "Đang kiểm tra…";
            }
            showFormFeedback(
                pf === "webcake"
                    ? "Checking connection…"
                    : isEnConn
                      ? "Testing connection…"
                      : "Đang kiểm tra kết nối…",
                "info",
            );
            try {
                if (pf === "webcake") {
                    const b = webcakePreviewBody();
                    if (!b.access_token || !b.refresh_token) {
                        showFormFeedback("Enter Access Token and Refresh Token to check.", "err");
                        return;
                    }
                    const r = await __settingsFetch("/api/settings/publishing-sites/webcake/test-connection", {
                        method: "POST",
                        headers: pubAuthJsonHeaders(),
                        body: JSON.stringify(b),
                    });
                    const data = await r.json().catch(() => ({}));
                    if (!r.ok) {
                        let err = fmtApiDetail(data.detail) || ("HTTP " + r.status);
                        if (r.status === 401 || r.status === 403) err = "Vui lòng đăng nhập (mục Tài khoản) rồi thử lại.";
                        showFormFeedback(err, "err");
                        return;
                    }
                    const kind = data.ok ? "ok" : "err";
                    const msg = data.message || (data.ok ? "Connection OK." : "Connection failed.");
                    showFormFeedback(msg, kind);
                    setMsg(msg, kind);
                    if (data.ok) {
                        rememberPubFormFields("webcake");
                        void loadModalCategories({ refresh: true });
                    }
                    return;
                }
                if (pf === "shopify") {
                    const b = shopifyPreviewBody();
                    if (!b.client_id || !b.client_secret) {
                        showFormFeedback("Enter Client ID and Client Secret to test.", "err");
                        return;
                    }
                    const r = await __settingsFetch("/api/settings/publishing-sites/shopify/test-connection", {
                        method: "POST",
                        headers: pubAuthJsonHeaders(),
                        body: JSON.stringify(b),
                    });
                    const data = await r.json().catch(() => ({}));
                    if (!r.ok) {
                        let err = fmtApiDetail(data.detail) || ("HTTP " + r.status);
                        if (r.status === 401 || r.status === 403) err = "Vui lòng đăng nhập (mục Tài khoản) rồi thử lại.";
                        showFormFeedback(err, "err");
                        return;
                    }
                    const kind = data.ok ? "ok" : "err";
                    const msg = data.message || (data.ok ? "Connection OK." : "Connection failed.");
                    showFormFeedback(msg, kind);
                    setMsg(msg, kind);
                    if (data.ok) {
                        rememberPubFormFields("shopify");
                        void loadModalCategories({ refresh: true });
                    }
                    return;
                }
                if (pf === "haravan") {
                    const b = haravanPreviewBody();
                    if (!b.private_token) {
                        showFormFeedback("Enter Private Token to test.", "err");
                        return;
                    }
                    const r = await __settingsFetch("/api/settings/publishing-sites/haravan/test-connection", {
                        method: "POST",
                        headers: pubAuthJsonHeaders(),
                        body: JSON.stringify(b),
                    });
                    const data = await r.json().catch(() => ({}));
                    if (!r.ok) {
                        let err = fmtApiDetail(data.detail) || ("HTTP " + r.status);
                        if (r.status === 401 || r.status === 403) err = "Vui lòng đăng nhập (mục Tài khoản) rồi thử lại.";
                        showFormFeedback(err, "err");
                        return;
                    }
                    const kind = data.ok ? "ok" : "err";
                    const msg = data.message || (data.ok ? "Connection OK." : "Connection failed.");
                    showFormFeedback(msg, kind);
                    setMsg(msg, kind);
                    if (data.ok) {
                        rememberPubFormFields("haravan");
                        void loadModalCategories({ refresh: true });
                    }
                    return;
                }
                if (pf === "wordpress") {
                    const b = wordpressPreviewBody();
                    if (!b.url || !b.username || !b.app_password) {
                        showFormFeedback("Nhập đủ URL, username và Application Password để kiểm tra.", "err");
                        return;
                    }
                    const r = await __settingsFetch("/api/settings/publishing-sites/wordpress/test-connection", {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify(b),
                    });
                    const data = await r.json().catch(() => ({}));
                    if (!r.ok) {
                        let err = fmtApiDetail(data.detail) || ("HTTP " + r.status);
                        if (r.status === 401 || r.status === 403) err = "Vui lòng đăng nhập (mục Tài khoản) rồi thử lại.";
                        showFormFeedback(err, "err");
                        return;
                    }
                    const kind = data.ok ? "ok" : "err";
                    const msg = data.message || (data.ok ? "Kết nối WordPress thành công." : "Không kết nối được.");
                    showFormFeedback(msg, kind);
                    setMsg(msg, kind);
                    if (data.ok) {
                        rememberPubFormFields("wordpress");
                        void loadModalCategories({ refresh: true });
                    }
                }
            } catch (_) {
                showFormFeedback("Lỗi mạng khi kiểm tra kết nối.", "err");
            } finally {
                hrvTestBtn.disabled = false;
                if (testLabel) {
                    testLabel.textContent =
                        oldLabel ||
                        (pf === "webcake"
                            ? "Check connection"
                            : pf === "haravan" || pf === "shopify"
                              ? "Test connection"
                              : "Kiểm tra kết nối");
                }
            }
        });
    }

    if (hrvSyncBtn) {
        hrvSyncBtn.addEventListener("click", async (e) => {
            e.preventDefault();
            e.stopPropagation();
            const pf = modalPlatform;
            const syncLabel = hrvSyncBtn.querySelector(".pub-conn-btn-label");
            const oldLabel = syncLabel ? syncLabel.textContent : "";
            hrvSyncBtn.disabled = true;
            if (syncLabel) {
                syncLabel.textContent =
                    pf === "webcake"
                        ? "Syncing…"
                        : pf === "haravan" || pf === "shopify"
                          ? "Syncing…"
                          : "Đang đồng bộ…";
            }
            showFormFeedback(
                pf === "webcake"
                    ? "Syncing categories…"
                    : pf === "haravan" || pf === "shopify"
                      ? "Syncing blogs…"
                      : "Đang đồng bộ bài viết…",
                "info",
            );
            try {
                if (pf === "webcake") {
                    const b = webcakePreviewBody();
                    if (!b.access_token || !b.refresh_token) {
                        showFormFeedback("Enter Access Token and Refresh Token to sync.", "err");
                        return;
                    }
                    const r = await __settingsFetch("/api/settings/publishing-sites/webcake/sync-categories", {
                        method: "POST",
                        headers: pubAuthJsonHeaders(),
                        body: JSON.stringify(b),
                    });
                    const data = await r.json().catch(() => ({}));
                    if (!r.ok) {
                        showFormFeedback(fmtApiDetail(data.detail) || ("HTTP " + r.status), "err");
                        return;
                    }
                    const kind = data.ok ? "ok" : "err";
                    const msg = data.message || "Sync done.";
                    showFormFeedback(msg, kind);
                    setMsg(msg, kind);
                    if (data.ok) rememberPubFormFields("webcake");
                    return;
                }
                if (pf === "shopify") {
                    const b = shopifyPreviewBody();
                    if (!b.client_id || !b.client_secret) {
                        showFormFeedback("Enter Client ID and Client Secret to sync.", "err");
                        return;
                    }
                    const r = await __settingsFetch("/api/settings/publishing-sites/shopify/sync-blogs", {
                        method: "POST",
                        headers: pubAuthJsonHeaders(),
                        body: JSON.stringify(b),
                    });
                    const data = await r.json().catch(() => ({}));
                    if (!r.ok) {
                        showFormFeedback(fmtApiDetail(data.detail) || ("HTTP " + r.status), "err");
                        return;
                    }
                    const kind = data.ok ? "ok" : "err";
                    const msg = data.message || "Sync done.";
                    showFormFeedback(msg, kind);
                    setMsg(msg, kind);
                    if (data.ok) rememberPubFormFields("shopify");
                    return;
                }
                if (pf === "haravan") {
                    const b = haravanPreviewBody();
                    if (!b.private_token) {
                        showFormFeedback("Enter Private Token to sync.", "err");
                        return;
                    }
                    const r = await __settingsFetch("/api/settings/publishing-sites/haravan/sync-blogs", {
                        method: "POST",
                        headers: pubAuthJsonHeaders(),
                        body: JSON.stringify(b),
                    });
                    const data = await r.json().catch(() => ({}));
                    if (!r.ok) {
                        showFormFeedback(fmtApiDetail(data.detail) || ("HTTP " + r.status), "err");
                        return;
                    }
                    const kind = data.ok ? "ok" : "err";
                    const msg = data.message || "Sync done.";
                    showFormFeedback(msg, kind);
                    setMsg(msg, kind);
                    if (data.ok) rememberPubFormFields("haravan");
                    return;
                }
                if (pf === "wordpress") {
                    const b = wordpressPreviewBody();
                    if (!b.url || !b.username || !b.app_password) {
                        showFormFeedback("Nhập đủ URL, username và Application Password để đồng bộ.", "err");
                        return;
                    }
                    const r = await __settingsFetch("/api/settings/publishing-sites/wordpress/sync-posts", {
                        method: "POST",
                        headers: pubAuthJsonHeaders(),
                        body: JSON.stringify(b),
                    });
                    const data = await r.json().catch(() => ({}));
                    if (!r.ok) {
                        showFormFeedback(fmtApiDetail(data.detail) || ("HTTP " + r.status), "err");
                        return;
                    }
                    const kind = data.ok ? "ok" : "err";
                    const msg = data.message || "Đồng bộ xong.";
                    showFormFeedback(msg, kind);
                    setMsg(msg, kind);
                    if (data.ok) rememberPubFormFields("wordpress");
                }
            } catch (_) {
                showFormFeedback("Lỗi mạng khi đồng bộ.", "err");
            } finally {
                hrvSyncBtn.disabled = false;
                if (syncLabel) {
                    syncLabel.textContent =
                        oldLabel ||
                        (pf === "webcake"
                            ? "Sync categories"
                            : pf === "haravan" || pf === "shopify"
                              ? "Sync Blogs"
                              : "Đồng bộ bài viết");
                }
            }
        });
    }

    if (inputUrl) {
        inputUrl.addEventListener("change", () => fillPassFromUrlHist(modalPlatform));
        inputUrl.addEventListener("blur", () => fillPassFromUrlHist(modalPlatform));
    }
    [inputName, inputUrl, inputUser].forEach((el) => {
        if (!el) return;
        el.addEventListener("blur", () => {
            if (modal.classList.contains("is-open")) rememberPubFormFields(modalPlatform);
        });
    });

    form.addEventListener("submit", async (e) => {
        e.preventDefault();
        showFormFeedback("", "");
        const pf = modalPlatform;
        const body = {
            platform: pf,
            name: inputName.value.trim(),
            url: pf === "shopify" || pf === "webcake" ? inputUrl.value.trim() : normPubUrl(inputUrl.value),
            username: pf === "wordpress" ? inputUser.value.trim() : "",
            app_password: inputPass.value.trim(),
            default_status: pf === "wordpress" ? inputStatus.value : "draft",
        };
        if (!body.name || !body.url) {
            const msg =
                pf === "haravan" || pf === "shopify" || pf === "webcake"
                    ? "Please enter display name and site URL."
                    : "Vui lòng nhập tên gợi nhớ và URL.";
            showFormFeedback(msg, "err");
            return;
        }
        if (pf === "wordpress") {
            body.app_password = String(body.app_password || "").replace(/\s+/g, "");
            if (!editingId && (!body.username || !body.app_password)) {
                showFormFeedback("Vui lòng nhập username và Application Password.", "err");
                return;
            }
        } else if (pf === "haravan") {
            if (!editingId && !body.app_password) {
                showFormFeedback("Please enter Private Token.", "err");
                return;
            }
        } else if (pf === "shopify") {
            const cid = shopifyClientId ? shopifyClientId.value.trim() : "";
            const sec = shopifyClientSecret ? shopifyClientSecret.value.trim() : "";
            const ver = shopifyApiVersion ? shopifyApiVersion.value : "2025-01";
            if (!cid) {
                showFormFeedback("Please enter Client ID.", "err");
                return;
            }
            if (!editingId && !sec) {
                showFormFeedback("Please enter Client Secret.", "err");
                return;
            }
            body.username = cid;
            if (sec) body.app_password = packShopifySecrets(sec, ver);
            else if (!editingId) {
                showFormFeedback("Please enter Client Secret.", "err");
                return;
            }
        } else if (pf === "webcake") {
            const access = webcakeAccess ? webcakeAccess.value.trim() : "";
            const refresh = webcakeRefresh ? webcakeRefresh.value.trim() : "";
            if (!editingId && (!access || !refresh)) {
                showFormFeedback("Please enter Access Token and Refresh Token.", "err");
                return;
            }
            if (access && refresh) {
                body.app_password = packWebcakeSecrets(access, refresh);
            } else if (!editingId) {
                showFormFeedback("Please enter Access Token and Refresh Token.", "err");
                return;
            }
        }
        submitBtn.disabled = true;
        try {
            let r;
            if (editingId) {
                const patch = { name: body.name, url: body.url, default_status: body.default_status };
                if (pf === "wordpress") patch.username = body.username;
                if (pf === "shopify" && body.username) patch.username = body.username;
                if (body.app_password) patch.app_password = body.app_password;
                r = await __settingsFetch("/api/settings/publishing-sites/" + encodeURIComponent(editingId), {
                    method: "PATCH",
                    headers: pubAuthJsonHeaders(),
                    body: JSON.stringify(patch),
                });
            } else {
                r = await __settingsFetch("/api/settings/publishing-sites", {
                    method: "POST",
                    headers: pubAuthJsonHeaders(),
                    body: JSON.stringify(body),
                });
            }
            if (!r.ok) {
                const j = await r.json().catch(() => ({}));
                showFormFeedback(fmtApiDetail(j.detail) || "Không lưu được site.", "err");
                return;
            }
            const data = await r.json();
            const savedId = (data && data.item && data.item.id) || editingId;
            rememberPubFormFields(pf);
            cache = { items: (data.summary && data.summary.items) || {}, counts: (data.summary && data.summary.counts) || {} };
            render();
            renderPubDatalists(pf);
            hideModal();
            const addedMsg =
                pf === "haravan" || pf === "shopify" || pf === "webcake"
                    ? "Store added. Verifying…"
                    : "Đã thêm site. Đang xác minh kết nối…";
            setMsg(editingId ? "Đã cập nhật." : addedMsg, "ok");
            if (savedId) {
                try { await verifySite(savedId, true, pf); } catch (_) {}
            }
        } catch (_) {
            showFormFeedback("Lỗi mạng khi lưu site.", "err");
        } finally {
            submitBtn.disabled = false;
        }
    });

    const verifySite = async (id, silent, pfHint) => {
        try {
            const pf = pfHint || currentPlatform;
            if (!silent) {
                const waitMsg =
                    pf === "haravan"
                        ? "Testing Haravan connection…"
                        : pf === "shopify"
                          ? "Testing Shopify connection…"
                          : pf === "webcake"
                            ? "Checking Webcake connection…"
                            : "Đang kiểm tra kết nối WordPress…";
                setMsg(waitMsg, "");
            }
            const r = await __settingsFetch("/api/settings/publishing-sites/" + encodeURIComponent(id) + "/verify", {
                method: "POST",
                headers: pubAuthHeaders(),
            });
            if (!r.ok) {
                setMsg("Kiểm tra thất bại (" + r.status + ").", "err");
                return;
            }
            const data = await r.json();
            cache = { items: (data.summary && data.summary.items) || {}, counts: (data.summary && data.summary.counts) || {} };
            render();
            const result = data.result || (data.item || {});
            if (result.verified) {
                setMsg(result.message || "Đã xác minh kết nối site.", "ok");
                try {
                    await __settingsFetch("/api/settings/publishing-sites/" + encodeURIComponent(id) + "/categories", {
                        method: "POST",
                        headers: pubAuthJsonHeaders(),
                        body: JSON.stringify({ refresh: true }),
                    });
                    notifyPubCategoriesChanged({ site_id: id, platform: pf });
                } catch (_) {}
            } else {
                setMsg((data.item && data.item.last_message) || result.message || "Không xác minh được kết nối.", "err");
            }
        } catch (_) {
            setMsg("Lỗi mạng khi kiểm tra site.", "err");
        }
    };

    sitesList.addEventListener("click", async (e) => {
        const btn = e.target.closest(".pub-action-btn");
        if (!btn) return;
        const card = e.target.closest(".pub-site-card");
        const id = card && card.getAttribute("data-id");
        if (!id) return;
        const act = btn.getAttribute("data-act");
        if (act === "verify") {
            const items = (cache.items && cache.items[currentPlatform]) || [];
            const st = items.find((x) => x.id === id);
            verifySite(id, false, st && st.platform);
            return;
        }
        if (act === "edit") {
            const items = (cache.items && cache.items[currentPlatform]) || [];
            const site = items.find((x) => x.id === id);
            if (site) showModal("edit", site);
            return;
        }
        if (act === "delete") {
            if (!confirm("Xóa site này khỏi danh sách?")) return;
            try {
                const r = await __settingsFetch("/api/settings/publishing-sites/" + encodeURIComponent(id), {
                    method: "DELETE",
                    headers: pubAuthHeaders(),
                });
                if (!r.ok) {
                    setMsg("Không xóa được site.", "err");
                    return;
                }
                const data = await r.json();
                cache = { items: (data.summary && data.summary.items) || {}, counts: (data.summary && data.summary.counts) || {} };
                render();
                setMsg("Đã xóa site.", "ok");
            } catch (_) {
                setMsg("Lỗi mạng khi xóa site.", "err");
            }
        }
    });

    const maybeLoadPub = () => {
        const h = (window.location.hash || "").split("?")[0];
        if (h === "#publishing") fetchSites();
    };
    window.addEventListener("hashchange", maybeLoadPub);
    maybeLoadPub();
    fetchSites();
    renderPubDatalists("wordpress");
    renderPubDatalists("haravan");
})();

/* ====================== SEOAuto SEO Helper (WordPress Plugin) ====================== */
(() => {
    const card = document.getElementById("wphCard");
    if (!card) return;

    const $ = (id) => document.getElementById(id);
    const statusBadge = $("wphStatusBadge");
    const entitlementWarn = $("wphEntitlementWarn");
    const entitlementMsg = $("wphEntitlementMsg");
    const connectedList = $("wphConnectedList");
    const connectBtn = $("wphConnectBtn");
    const checkBtn = $("wphCheckBtn");
    const disconnectBtn = $("wphDisconnectBtn");
    const connectAnotherBtn = $("wphConnectAnotherBtn");
    const pairingPanel = $("wphPairingPanel");
    const pairingCodeEl = $("wphPairingCode");
    const copyBtn = $("wphCopyBtn");
    const countdownEl = $("wphCountdown");
    const regenBtn = $("wphRegenBtn");
    const msgEl = $("wphMsg");

    const state = {
        connections: [],
        entitlement: null,
        selectedId: null,
        pairing: null,
        pollTimer: null,
        countdownTimer: null,
        createBusy: false,
        checkBusy: false,
        disconnectBusy: false,
        abortCtrl: null,
    };

    const escapeHtml = (s) => String(s || "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

    const setMsg = (text, kind) => {
        if (!msgEl) return;
        msgEl.textContent = text || "";
        msgEl.classList.remove("ok", "err");
        if (kind) msgEl.classList.add(kind);
    };

    const fmtDetail = (data) => {
        if (!data) return "Lỗi không xác định.";
        if (typeof data === "string") return data;
        if (data.message) return String(data.message);
        if (data.detail) return fmtDetail(data.detail);
        return "Lỗi không xác định.";
    };

    const fmtDate = (iso) => {
        if (!iso) return "—";
        try {
            const d = new Date(iso);
            if (Number.isNaN(d.getTime())) return "—";
            return d.toLocaleString("vi-VN");
        } catch (_) {
            return "—";
        }
    };

    const fmtCountdown = (sec) => {
        const s = Math.max(0, Number(sec) || 0);
        const m = Math.floor(s / 60);
        const r = s % 60;
        return `${m}:${String(r).padStart(2, "0")}`;
    };

    const stopTimers = () => {
        if (state.pollTimer) {
            clearInterval(state.pollTimer);
            state.pollTimer = null;
        }
        if (state.countdownTimer) {
            clearInterval(state.countdownTimer);
            state.countdownTimer = null;
        }
        if (state.abortCtrl) {
            try { state.abortCtrl.abort(); } catch (_) {}
            state.abortCtrl = null;
        }
    };

    const selectedConnection = () => state.connections.find((c) => Number(c.id) === Number(state.selectedId)) || state.connections[0] || null;

    const renderConnections = () => {
        const items = state.connections || [];
        const hasConn = items.length > 0;
        if (statusBadge) statusBadge.hidden = !hasConn;
        if (connectedList) {
            connectedList.hidden = !hasConn;
            connectedList.innerHTML = items.map((c) => {
                const ent = c.entitlement || {};
                const entLabel = ent.allowed ? (ent.plan_code || "Hợp lệ") : (ent.reason || "Không hợp lệ");
                const selected = Number(c.id) === Number((selectedConnection() || {}).id);
                return `<article class="wph-site${selected ? " is-selected" : ""}" data-id="${escapeHtml(c.id)}">
                    <div class="wph-site-head">
                        <div class="wph-site-domain">${escapeHtml(c.domain || "—")}</div>
                    </div>
                    <a class="wph-site-url" href="${escapeHtml(c.site_url || "#")}" target="_blank" rel="noopener noreferrer">${escapeHtml(c.site_url || "")}</a>
                    <div class="wph-site-meta">
                        <div>Plugin: <strong>${escapeHtml(c.plugin_version || "—")}</strong></div>
                        <div>WordPress: <strong>${escapeHtml(c.wp_version || "—")}</strong></div>
                        <div>Plugin SEO: <strong>${escapeHtml(c.seo_plugin || "—")}</strong></div>
                        <div>Kết nối gần nhất: <strong>${escapeHtml(fmtDate(c.last_seen_at || c.connected_at))}</strong></div>
                        <div>Entitlement: <strong>${escapeHtml(entLabel)}</strong></div>
                    </div>
                </article>`;
            }).join("");
        }

        const ent = state.entitlement || {};
        const canConnect = Boolean(ent.can_connect) || Boolean(ent.allowed);
        const showUpgrade = !canConnect && Boolean(ent.message);

        if (entitlementWarn) {
            entitlementWarn.hidden = !showUpgrade;
            entitlementWarn.setAttribute("aria-hidden", showUpgrade ? "false" : "true");
        }
        if (entitlementMsg && ent.message) entitlementMsg.textContent = ent.message;
        if (entitlementMsg && canConnect) entitlementMsg.textContent = "";

        if (connectBtn) {
            connectBtn.hidden = hasConn;
            connectBtn.disabled = !canConnect || state.createBusy;
        }
        if (connectAnotherBtn) {
            connectAnotherBtn.hidden = !hasConn;
            connectAnotherBtn.disabled = !canConnect || state.createBusy;
        }
        if (checkBtn) {
            checkBtn.hidden = !hasConn;
            checkBtn.disabled = !hasConn || state.checkBusy;
        }
        if (disconnectBtn) {
            disconnectBtn.hidden = !hasConn;
            disconnectBtn.disabled = !hasConn || state.disconnectBusy;
        }
    };

    const applySummary = (data) => {
        state.connections = Array.isArray(data.connections) ? data.connections : [];
        state.entitlement = data.entitlement || state.entitlement;
        if (!state.selectedId && state.connections.length) {
            state.selectedId = state.connections[0].id;
        } else if (state.selectedId && !state.connections.some((c) => Number(c.id) === Number(state.selectedId))) {
            state.selectedId = state.connections[0] ? state.connections[0].id : null;
        }
        renderConnections();
    };

    const fetchSummary = async () => {
        const r = await window.__settingsFetch("/api/wordpress-plugin/connections", {
            headers: window.__settingsAuthHeaders(),
        });
        if (!r.ok) {
            const err = await r.json().catch(() => ({}));
            throw new Error(fmtDetail(err));
        }
        const data = await r.json();
        applySummary(data);
        return data;
    };

    const showPairing = (payload) => {
        state.pairing = payload;
        if (pairingPanel) pairingPanel.hidden = false;
        if (pairingCodeEl) pairingCodeEl.textContent = payload.code || "—";
        if (regenBtn) regenBtn.hidden = true;
        startCountdown(payload.expires_at, Number(payload.expires_in_seconds || 600));
        startPoll(payload.pairing_code_id);
    };

    const hidePairing = () => {
        state.pairing = null;
        if (pairingPanel) pairingPanel.hidden = true;
        stopTimers();
    };

    const startCountdown = (expiresAt, fallbackSec) => {
        if (state.countdownTimer) clearInterval(state.countdownTimer);
        const endMs = expiresAt ? new Date(expiresAt).getTime() : Date.now() + (fallbackSec * 1000);
        const tick = () => {
            const left = Math.max(0, Math.floor((endMs - Date.now()) / 1000));
            if (countdownEl) countdownEl.textContent = fmtCountdown(left);
            if (left <= 0) {
                if (regenBtn) regenBtn.hidden = false;
                if (state.pollTimer) {
                    clearInterval(state.pollTimer);
                    state.pollTimer = null;
                }
            }
        };
        tick();
        state.countdownTimer = setInterval(tick, 1000);
    };

    const startPoll = (pairingCodeId) => {
        if (!pairingCodeId) return;
        if (state.pollTimer) clearInterval(state.pollTimer);
        const poll = async () => {
            try {
                const r = await window.__settingsFetch(`/api/wordpress-plugin/pairing-codes/${encodeURIComponent(pairingCodeId)}`, {
                    headers: window.__settingsAuthHeaders(),
                });
                if (!r.ok) return;
                const data = await r.json();
                if (data.status === "consumed" && data.connection) {
                    stopTimers();
                    hidePairing();
                    applySummary({
                        connections: [data.connection, ...state.connections.filter((c) => Number(c.id) !== Number(data.connection.id))],
                        entitlement: state.entitlement,
                    });
                    setMsg("Đã kết nối WordPress thành công.", "ok");
                    await fetchSummary();
                } else if (data.status === "expired") {
                    if (regenBtn) regenBtn.hidden = false;
                    if (countdownEl) countdownEl.textContent = "0:00";
                }
            } catch (_) {}
        };
        poll();
        state.pollTimer = setInterval(poll, 3000);
    };

    const createPairingCode = async () => {
        if (state.createBusy) return;
        const ent = state.entitlement || {};
        if (!ent.can_connect) {
            setMsg(ent.message || "Gói hiện tại chưa hỗ trợ SEOAuto SEO Helper.", "err");
            return;
        }
        state.createBusy = true;
        if (connectBtn) connectBtn.disabled = true;
        if (connectAnotherBtn) connectAnotherBtn.disabled = true;
        setMsg("Đang tạo mã kết nối…");
        try {
            state.abortCtrl = new AbortController();
            const r = await window.__settingsFetch("/api/wordpress-plugin/pairing-codes", {
                method: "POST",
                headers: window.__settingsAuthJson(),
                body: JSON.stringify({}),
                signal: state.abortCtrl.signal,
            });
            const data = await r.json().catch(() => ({}));
            if (!r.ok) {
                setMsg(fmtDetail(data), "err");
                return;
            }
            showPairing(data);
            setMsg("Mã kết nối đã sẵn sàng — dán vào plugin WordPress.", "ok");
        } catch (e) {
            if (e && e.name !== "AbortError") setMsg(e.message || "Không tạo được mã kết nối.", "err");
        } finally {
            state.createBusy = false;
            state.abortCtrl = null;
            renderConnections();
        }
    };

    const copyPairingCode = async () => {
        const code = state.pairing && state.pairing.code;
        if (!code || !copyBtn) return;
        const idle = copyBtn.getAttribute("data-idle-label") || "Sao chép mã";
        const busy = copyBtn.getAttribute("data-busy-label") || "Đã sao chép";
        try {
            await navigator.clipboard.writeText(code);
            copyBtn.textContent = busy;
            setTimeout(() => { copyBtn.textContent = idle; }, 2000);
        } catch (_) {
            setMsg("Không sao chép được — hãy chọn và copy thủ công.", "err");
        }
    };

    const checkSelected = async () => {
        const conn = selectedConnection();
        if (!conn || state.checkBusy) return;
        state.checkBusy = true;
        if (checkBtn) checkBtn.disabled = true;
        setMsg("Đang kiểm tra kết nối…");
        try {
            const r = await window.__settingsFetch(`/api/wordpress-plugin/connections/${encodeURIComponent(conn.id)}/check`, {
                method: "POST",
                headers: window.__settingsAuthHeaders(),
            });
            const data = await r.json().catch(() => ({}));
            if (!r.ok) {
                setMsg(fmtDetail(data), "err");
                return;
            }
            if (data.connection) {
                state.connections = state.connections.map((c) => (Number(c.id) === Number(data.connection.id) ? data.connection : c));
                renderConnections();
            }
            setMsg(data.ok ? "Kết nối plugin hoạt động bình thường." : (data.connection && data.connection.check_message) || "Không kiểm tra được plugin.", data.ok ? "ok" : "err");
        } catch (e) {
            setMsg(e.message || "Lỗi mạng khi kiểm tra kết nối.", "err");
        } finally {
            state.checkBusy = false;
            renderConnections();
        }
    };

    const disconnectSelected = async () => {
        const conn = selectedConnection();
        if (!conn || state.disconnectBusy) return;
        if (!confirm(`Ngắt kết nối plugin với ${conn.domain || "website này"}? Dữ liệu WordPress sẽ không bị xóa.`)) return;
        state.disconnectBusy = true;
        if (disconnectBtn) disconnectBtn.disabled = true;
        setMsg("Đang ngắt kết nối…");
        try {
            const r = await window.__settingsFetch(`/api/wordpress-plugin/connections/${encodeURIComponent(conn.id)}`, {
                method: "DELETE",
                headers: window.__settingsAuthHeaders(),
            });
            const data = await r.json().catch(() => ({}));
            if (!r.ok) {
                setMsg(fmtDetail(data), "err");
                return;
            }
            if (data.summary) applySummary(data.summary);
            else await fetchSummary();
            hidePairing();
            setMsg("Đã ngắt kết nối plugin.", "ok");
        } catch (e) {
            setMsg(e.message || "Lỗi mạng khi ngắt kết nối.", "err");
        } finally {
            state.disconnectBusy = false;
            renderConnections();
        }
    };

    if (connectBtn) connectBtn.addEventListener("click", createPairingCode);
    if (connectAnotherBtn) connectAnotherBtn.addEventListener("click", createPairingCode);
    if (copyBtn) copyBtn.addEventListener("click", copyPairingCode);
    if (regenBtn) regenBtn.addEventListener("click", createPairingCode);
    if (checkBtn) checkBtn.addEventListener("click", checkSelected);
    if (disconnectBtn) disconnectBtn.addEventListener("click", disconnectSelected);
    if (connectedList) {
        connectedList.addEventListener("click", (e) => {
            const cardEl = e.target.closest(".wph-site");
            if (!cardEl) return;
            state.selectedId = cardEl.getAttribute("data-id");
            renderConnections();
        });
    }

    const maybeLoad = () => {
        const h = (window.location.hash || "").split("?")[0];
        if (h === "#publishing") {
            fetchSummary().catch((e) => setMsg(e.message || "Không tải trạng thái plugin.", "err"));
        }
    };
    window.addEventListener("hashchange", maybeLoad);
    window.addEventListener("wph-tab-show", maybeLoad);
    window.addEventListener("beforeunload", stopTimers);
    window.addEventListener("pagehide", stopTimers);
    window.addEventListener("digiseo-auth-change", maybeLoad);
    // Retry once auth token is ready (token may arrive after first paint).
    window.setTimeout(maybeLoad, 400);
    window.setTimeout(maybeLoad, 1200);
    maybeLoad();
})();

/* ====================== System settings ====================== */
(() => {
    const SYS_LS = "digiseo_system_prefs_v1";

    const themeGrid = document.getElementById("sysThemeGrid");
    const langGrid = document.getElementById("sysLangGrid");
    const launchToggle = document.getElementById("sysLaunchToggle");
    const batchEl = document.getElementById("sysBatchSize");
    const retriesEl = document.getElementById("sysMaxRetries");
    const stuckEl = document.getElementById("sysStuckTimeout");
    const saveMsg = document.getElementById("sysSaveMsg");
    if (!themeGrid) return;

    let prefs = {
        theme: "dark",
        language: "en",
        launch_on_startup: false,
        batch_size: 5,
        max_retries: 3,
        stuck_timeout_minutes: 30,
    };
    let saveTimer = null;

    const t = (key) => {
        const L = prefs.language === "vi" ? "vi" : "en";
        const full = key.startsWith("system.") || key.startsWith("nav.") ? key : "system." + key;
        return window.DigiSeoI18n ? window.DigiSeoI18n.t(L, full) : key;
    };

    const applyPageI18n = () => {
        if (window.DigiSeoI18n) window.DigiSeoI18n.apply(prefs.language === "vi" ? "vi" : "en");
    };

    const setMsg = (text, kind) => {
        if (!saveMsg) return;
        saveMsg.textContent = text || "";
        saveMsg.classList.remove("ok", "err");
        if (kind) saveMsg.classList.add(kind);
    };

    const renderUi = () => {
        themeGrid.querySelectorAll("[data-theme-choice]").forEach((btn) => {
            const on = btn.getAttribute("data-theme-choice") === prefs.theme;
            btn.classList.toggle("is-active", on);
            btn.setAttribute("aria-pressed", on ? "true" : "false");
        });
        langGrid.querySelectorAll("[data-lang-choice]").forEach((btn) => {
            const code = btn.getAttribute("data-lang-choice");
            const on = code === prefs.language;
            btn.classList.toggle("is-active", on);
            btn.setAttribute("aria-pressed", on ? "true" : "false");
            const badge = btn.querySelector("[data-lang-badge]");
            if (badge) badge.hidden = !on;
        });
        if (launchToggle) {
            launchToggle.classList.toggle("is-on", !!prefs.launch_on_startup);
            launchToggle.setAttribute("aria-pressed", prefs.launch_on_startup ? "true" : "false");
        }
        if (batchEl) batchEl.value = String(prefs.batch_size);
        if (retriesEl) retriesEl.value = String(prefs.max_retries);
        if (stuckEl) stuckEl.value = String(prefs.stuck_timeout_minutes);
        applyPageI18n();
        if (window.__digiseoApplySystemPrefs) window.__digiseoApplySystemPrefs(prefs);
    };

    const scheduleSave = () => {
        if (saveTimer) clearTimeout(saveTimer);
        saveTimer = setTimeout(savePrefs, 400);
    };

    const collectPrefs = () => ({
        theme: prefs.theme,
        language: prefs.language,
        launch_on_startup: !!prefs.launch_on_startup,
        batch_size: parseInt(batchEl && batchEl.value, 10) || 5,
        max_retries: parseInt(retriesEl && retriesEl.value, 10) || 3,
        stuck_timeout_minutes: parseInt(stuckEl && stuckEl.value, 10) || 30,
    });

    const savePrefs = async () => {
        const body = collectPrefs();
        prefs = { ...prefs, ...body };
        try {
            localStorage.setItem(SYS_LS, JSON.stringify(prefs));
        } catch (_) {}
        if (window.__digiseoApplySystemPrefs) window.__digiseoApplySystemPrefs(prefs);
        try {
            const r = await __settingsFetch("/api/settings/system", {
                method: "PATCH",
                headers: window.__settingsAuthJson(),
                body: JSON.stringify(body),
            });
            if (r.status === 401 || r.status === 403) {
                setMsg(t("need_login"), "err");
                return;
            }
            if (!r.ok) {
                setMsg(t("save_err"), "err");
                return;
            }
            const data = await r.json().catch(() => ({}));
            if (data.settings) prefs = data.settings;
            renderUi();
            setMsg(t("saved"), "ok");
        } catch (_) {
            setMsg(t("save_err"), "err");
        }
    };

    const loadPrefs = async () => {
        try {
            const raw = localStorage.getItem(SYS_LS);
            if (raw) prefs = { ...prefs, ...JSON.parse(raw) };
        } catch (_) {}
        try {
            const r = await __settingsFetch("/api/settings/system", { headers: window.__settingsAuthHeaders() });
            if (r.ok) {
                const data = await r.json();
                if (data.settings) prefs = { ...prefs, ...data.settings };
            }
        } catch (_) {}
        renderUi();
    };

    themeGrid.addEventListener("click", (e) => {
        const btn = e.target.closest("[data-theme-choice]");
        if (!btn) return;
        prefs.theme = btn.getAttribute("data-theme-choice") || "dark";
        renderUi();
        scheduleSave();
    });
    langGrid.addEventListener("click", (e) => {
        const btn = e.target.closest("[data-lang-choice]");
        if (!btn) return;
        prefs.language = btn.getAttribute("data-lang-choice") || "en";
        renderUi();
        scheduleSave();
    });
    if (launchToggle) {
        launchToggle.addEventListener("click", () => {
            prefs.launch_on_startup = !prefs.launch_on_startup;
            renderUi();
            scheduleSave();
        });
    }
    [batchEl, retriesEl, stuckEl].forEach((el) => {
        if (!el) return;
        el.addEventListener("change", scheduleSave);
        el.addEventListener("blur", scheduleSave);
    });

    const maybeLoad = () => {
        if ((window.location.hash || "").split("?")[0] === "#system") loadPrefs();
    };
    window.addEventListener("hashchange", maybeLoad);
    if ((window.location.hash || "").split("?")[0] === "#system") loadPrefs();
})();

/* ====================== Chatbot CSKH email notifications ====================== */
(() => {
    const section = document.getElementById("email-notifications");
    if (!section) return;
    const enabledEl = document.getElementById("cskhNotifyEnabled");
    const emailEl = document.getElementById("cskhNotifyEmail");
    const delayGrid = document.getElementById("cskhNotifyDelayGrid");
    const msgEl = document.getElementById("cskhNotifySaveMsg");
    const DELAYS = [0, 120, 300, 600];
    let prefs = { enabled: true, notify_email: "", delay_seconds: 120, account_email: "" };
    let saveTimer = null;
    let loaded = false;

    const setMsg = (text, kind) => {
        if (!msgEl) return;
        msgEl.textContent = text || "";
        msgEl.classList.toggle("ok", kind === "ok");
        msgEl.classList.toggle("err", kind === "err");
    };

    const render = () => {
        if (enabledEl) {
            enabledEl.classList.toggle("is-on", !!prefs.enabled);
            enabledEl.setAttribute("aria-pressed", prefs.enabled ? "true" : "false");
        }
        if (emailEl && document.activeElement !== emailEl) {
            emailEl.value = prefs.notify_email || prefs.account_email || "";
            emailEl.placeholder = prefs.account_email || "";
        }
        if (delayGrid) {
            delayGrid.querySelectorAll("[data-cskh-delay]").forEach((btn) => {
                const on = String(prefs.delay_seconds) === String(btn.getAttribute("data-cskh-delay"));
                btn.classList.toggle("is-active", on);
                btn.setAttribute("aria-pressed", on ? "true" : "false");
            });
        }
    };

    const save = async () => {
        const body = {
            enabled: !!prefs.enabled,
            notify_email: ((emailEl && emailEl.value) || "").trim(),
            delay_seconds: DELAYS.includes(prefs.delay_seconds) ? prefs.delay_seconds : 120,
        };
        try {
            const r = await __settingsFetch("/api/settings/chatbot-email-notify", {
                method: "PATCH",
                headers: window.__settingsAuthJson(),
                body: JSON.stringify(body),
            });
            if (r.status === 401 || r.status === 403) {
                setMsg("Vui lòng đăng nhập để lưu cài đặt.", "err");
                return;
            }
            const data = await r.json().catch(() => ({}));
            if (!r.ok) {
                setMsg((data && data.detail) || "Không lưu được cài đặt.", "err");
                return;
            }
            if (data.settings) prefs = { ...prefs, ...data.settings };
            render();
            setMsg("Đã lưu.", "ok");
        } catch (_) {
            setMsg("Không lưu được cài đặt.", "err");
        }
    };

    const scheduleSave = () => {
        if (saveTimer) clearTimeout(saveTimer);
        saveTimer = setTimeout(save, 400);
    };

    const load = async () => {
        try {
            const r = await __settingsFetch("/api/settings/chatbot-email-notify", {
                headers: window.__settingsAuthHeaders(),
            });
            if (r.ok) {
                const data = await r.json();
                if (data.settings) prefs = { ...prefs, ...data.settings };
            }
        } catch (_) {}
        loaded = true;
        render();
    };

    if (enabledEl) {
        enabledEl.addEventListener("click", () => {
            prefs.enabled = !prefs.enabled;
            render();
            scheduleSave();
        });
    }
    if (emailEl) {
        emailEl.addEventListener("change", scheduleSave);
        emailEl.addEventListener("blur", scheduleSave);
    }
    if (delayGrid) {
        delayGrid.addEventListener("click", (e) => {
            const btn = e.target.closest("[data-cskh-delay]");
            if (!btn) return;
            const n = parseInt(btn.getAttribute("data-cskh-delay"), 10);
            if (!DELAYS.includes(n)) return;
            prefs.delay_seconds = n;
            render();
            scheduleSave();
        });
    }

    const maybeLoad = () => {
        if ((window.location.hash || "").split("?")[0] === "#email-notifications") load();
    };
    window.addEventListener("hashchange", maybeLoad);
    if ((window.location.hash || "").split("?")[0] === "#email-notifications") load();
    else if (!loaded) load();
})();
