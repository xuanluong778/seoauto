
    const allArticlesBackdropEl = byId("allArticlesBackdrop");
    const allArticlesModalEl = byId("allArticlesModal");
    const allArticlesListEl = byId("allArticlesList");
    const allArticlesSearchEl = byId("allArticlesSearch");
    const allArticlesEmptyEl = byId("allArticlesEmpty");
    const closeAllArticlesModal = () => {
        if (allArticlesBackdropEl) allArticlesBackdropEl.classList.remove("open");
        if (allArticlesModalEl) {
            allArticlesModalEl.classList.remove("open");
            allArticlesModalEl.setAttribute("aria-hidden", "true");
        }
    };
    const scrollSidebarActiveProject = () => {
        try {
            const el = projectList && projectList.querySelector(".project-item.active");
            if (el) el.scrollIntoView({ block: "nearest", behavior: "smooth" });
        } catch (_) {}
    };
    const selectProjectFromAllModal = async (projectId) => {
        const pid = String(projectId || "").trim();
        if (!pid) return;
        closeAllArticlesModal();
        closeSiteArticlesModal();
        closeArticleDetailModal();
        activeProjectId = pid;
        try {
            renderProjects();
            renderConnectedSitesPanel();
        } catch (_) {}
        setContentAiMainView("single");
        if (railNav) {
            railNav.querySelectorAll(".content-ai-nav-item").forEach((n) => n.classList.remove("active"));
        }
        await loadProject(pid);
        try {
            renderProjects();
            scrollSidebarActiveProject();
        } catch (_) {}
        window.setTimeout(() => {
            if (contentAiSinglePanel) {
                contentAiSinglePanel.scrollIntoView({ behavior: "smooth", block: "start" });
            }
            const pk = byId("primaryKeyword");
            if (pk) pk.focus({ preventScroll: true });
        }, 320);
    };
    const loadProjectIntoWriteTab = async (projectId) => selectProjectFromAllModal(projectId);

    window.DigiSeoLoadContentAiProject = async function (projectId) {
        const pid = String(projectId || "").trim();
        if (!pid) return;
        await loadProjectIntoWriteTab(pid);
        try {
            saveFormState();
        } catch (_) {}
    };
    const allProjectsModalCountEl = byId("allProjectsModalCount");
    const updateAllPublishingSitesModalCount = (shown, total) => {
        if (!allProjectsModalCountEl) return;
        if (!total) {
            allProjectsModalCountEl.hidden = true;
            return;
        }
        allProjectsModalCountEl.hidden = false;
        allProjectsModalCountEl.textContent =
            shown === total
                ? `Hiển thị ${total} website`
                : `Hiển thị ${shown} / ${total} website (đang lọc tìm kiếm)`;
    };
    const renderAllPublishingSitesList = () => {
        if (!allArticlesListEl) return;
        const q = String((allArticlesSearchEl && allArticlesSearchEl.value) || "")
            .trim()
            .toLowerCase();
        let sites = collectConnectedSites();
        const totalAll = sites.length;
        if (q) {
            sites = sites.filter((it) => {
                let host = String(it.url || "").toLowerCase();
                try {
                    host = (new URL(it.url).host || host).toLowerCase();
                } catch (_) {}
                return host.includes(q) || String(it.url || "").toLowerCase().includes(q);
            });
        }
        updateAllPublishingSitesModalCount(sites.length, totalAll);
        allArticlesListEl.innerHTML = "";
        if (!sites.length) {
            if (allArticlesEmptyEl) allArticlesEmptyEl.hidden = false;
            return;
        }
        if (allArticlesEmptyEl) allArticlesEmptyEl.hidden = true;
        const filterKey = String(_projectsSiteFilterBase || "").toLowerCase();
        const wpNorm = normalizeWpUrl(byId("wpUrl") && byId("wpUrl").value.trim());
        const tgNorm = normalizeTargetBase(byId("targetWebsite") && byId("targetWebsite").value.trim());
        const activeKeys = new Set([wpNorm, tgNorm, filterKey].filter(Boolean).map((u) => u.toLowerCase()));
        const platLbl = { shopify: "Shopify", haravan: "Haravan", webcake: "Webcake" };
        sites.forEach((it) => {
            const btn = document.createElement("button");
            btn.type = "button";
            const key = String(it.url).toLowerCase();
            btn.className = `all-publishing-site-item${activeKeys.has(key) || (filterKey && key === filterKey) ? " active" : ""}`;
            btn.setAttribute("role", "listitem");
            const dot = document.createElement("span");
            dot.className = "dot";
            const body = document.createElement("div");
            body.style.flex = "1";
            const hostEl = document.createElement("div");
            hostEl.className = "host";
            try {
                hostEl.textContent = new URL(it.url).host || it.url;
            } catch (_) {
                hostEl.textContent = it.url;
            }
            const badges = document.createElement("div");
            badges.className = "badges";
            if (it.wp) {
                const b = document.createElement("span");
                b.className = "connected-site-badge wp";
                b.textContent = "WP";
                badges.appendChild(b);
            }
            (it.platforms || []).forEach((pl) => {
                const b = document.createElement("span");
                b.className = `connected-site-badge plat plat-${pl}`;
                b.textContent = platLbl[pl] || pl;
                badges.appendChild(b);
            });
            body.appendChild(hostEl);
            body.appendChild(badges);
            btn.appendChild(dot);
            btn.appendChild(body);
            btn.title = it.url;
            btn.addEventListener("click", async () => {
                closeAllArticlesModal();
                await applyConnectedSiteSelection(it, { openArticles: false });
            });
            allArticlesListEl.appendChild(btn);
        });
    };
    const openAllPublishingSitesModal = async () => {
        if (allArticlesSearchEl) allArticlesSearchEl.value = "";
        const titleEl = byId("allPublishingSitesModalTitle");
        if (titleEl) titleEl.textContent = "Tất cả website đăng bài";
        try {
            await fetchSettingsPublishingSites();
            renderConnectedSitesPanel();
        } catch (_) {}
        renderAllPublishingSitesList();
        if (allArticlesBackdropEl) allArticlesBackdropEl.classList.add("open");
        if (allArticlesModalEl) {
            allArticlesModalEl.classList.add("open");
            allArticlesModalEl.setAttribute("aria-hidden", "false");
        }
        if (allArticlesSearchEl) {
            window.setTimeout(() => allArticlesSearchEl.focus(), 120);
        }
    };
    const stopBulkPoll = () => {
        if (_bulkPollTimer) {
            clearInterval(_bulkPollTimer);
            _bulkPollTimer = null;
        }
        const stopBtn = byId("btnBulkWriteStopPoll");
        if (stopBtn) stopBtn.hidden = true;
        const stopBar = byId("btnBulkV2StopWrite");
        if (stopBar) {
            stopBar.disabled = false;
            stopBar.classList.remove("is-busy");
        }
    };
    const getActiveBulkJobId = () => {
        try {
            return String(localStorage.getItem(BULK_JOB_STORAGE_KEY()) || "").trim();
        } catch (_) {
            return "";
        }
    };
    const cancelBulkWriteJob = async () => {
        const jid = getActiveBulkJobId();
        if (!jid) {
            stopBulkPoll();
            appendBulkLog("Không có job đang chạy trên trình duyệt.");
            try {
                if (window.ContentAiBulkUi && window.ContentAiBulkUi.setStep) {
                    window.ContentAiBulkUi.setStep("setup");
                }
            } catch (_) {}
            return;
        }
        const ok = window.confirm(
            "Dừng viết hàng loạt?\nBài đang viết có thể hoàn tất; các bài còn lại sẽ không chạy.\nBạn có thể setup lại rồi viết tiếp."
        );
        if (!ok) return;
        appendBulkLog("Đang gửi lệnh dừng viết…");
        try {
            const res = await fetch(`/content-ai/bulk-jobs/${encodeURIComponent(jid)}/cancel`, {
                method: "POST",
                headers: authJsonHeaders(),
                body: "{}",
            });
            const data = await res.json().catch(() => ({}));
            if (!res.ok) {
                throw new Error((data && data.detail) ? String(data.detail) : `Lỗi HTTP ${res.status}`);
            }
            appendBulkLog(String((data && data.message) || "Đã dừng viết hàng loạt."));
            if (data.result && Array.isArray(data.result.items)) {
                renderBulkJobItems(data.result.items, { mode: "merge" });
            } else if (bulkJobStatus) {
                bulkJobStatus.textContent = String((data && data.message) || "Đã dừng");
            }
            // Pull latest items once after cancel.
            try {
                const pollRes = await fetch(`/content-ai/bulk-jobs/${encodeURIComponent(jid)}?ts=${Date.now()}`, {
                    headers: authHeaders(),
                });
                const pollData = await pollRes.json().catch(() => ({}));
                if (pollRes.ok && pollData.result && Array.isArray(pollData.result.items)) {
                    renderBulkJobItems(pollData.result.items, { mode: "merge" });
                }
            } catch (_) {}
            try {
                localStorage.setItem(BULK_LAST_JOB_KEY(), jid);
                localStorage.removeItem(BULK_JOB_STORAGE_KEY());
            } catch (_) {}
            scheduleSaveBulkState();
            stopBulkPoll();
            try {
                if (window.ContentAiBulkUi && window.ContentAiBulkUi.setStep) {
                    window.ContentAiBulkUi.setStep("setup");
                }
            } catch (_) {}
            if (msg) msg.textContent = "Đã dừng viết — bạn có thể setup lại rồi bấm viết tiếp.";
        } catch (e) {
            appendBulkLog(`Dừng viết thất bại: ${String(e.message || e)}`);
            // Still stop local polling so UI unlocks.
            stopBulkPoll();
        }
    };
    const pollBulkJob = async (jobId) => {
        const jid = String(jobId || "").trim();
        if (!jid) return;
        try {
            const res = await fetch(`/content-ai/bulk-jobs/${encodeURIComponent(jid)}?ts=${Date.now()}`, {
                headers: authHeaders(),
            });
            const data = await res.json().catch(() => ({}));
            if (res.status === 404) {
                appendBulkLog("Job không còn trên server — đã xóa khỏi bộ nhớ trình duyệt.");
                try {
                    localStorage.removeItem(BULK_JOB_STORAGE_KEY());
                    localStorage.removeItem(BULK_LAST_JOB_KEY());
                } catch (_) {}
                stopBulkPoll();
                if (bulkJobStatus) bulkJobStatus.textContent = "Job đã hết hạn hoặc không tồn tại.";
                return;
            }
            if (!res.ok) throw new Error((data && data.detail) ? data.detail : "Poll failed");
            const pct = Number(data.progress) || 0;
            if (bulkJobProgress) bulkJobProgress.hidden = false;
            if (bulkJobProgressFill) bulkJobProgressFill.style.width = `${pct}%`;
            if (bulkJobPct) bulkJobPct.textContent = `${pct}%`;
            if (bulkJobStatus) bulkJobStatus.textContent = data.message || data.state || "";
            if (data.result && Array.isArray(data.result.items) && data.result.items.length) {
                // Merge so unselected / previously written rows keep their UI status.
                renderBulkJobItems(data.result.items, { mode: "merge" });
            }
            if (data.state === "SUCCESS") {
                appendBulkLog(`Hoàn tất: ${(data.result && data.result.success) || 0}/${(data.result && data.result.total) || "?"} bài.`);
                stopBulkPoll();
                try {
                    localStorage.setItem(BULK_LAST_JOB_KEY(), jid);
                    localStorage.removeItem(BULK_JOB_STORAGE_KEY());
                } catch (_) {}
                scheduleSaveBulkState();
                await refreshProjects(true);
                return;
            }
            if (data.state === "CANCELLED") {
                appendBulkLog(data.message || data.error || "Đã dừng viết hàng loạt.");
                stopBulkPoll();
                try {
                    localStorage.setItem(BULK_LAST_JOB_KEY(), jid);
                    localStorage.removeItem(BULK_JOB_STORAGE_KEY());
                } catch (_) {}
                scheduleSaveBulkState();
                try {
                    if (window.ContentAiBulkUi && window.ContentAiBulkUi.setStep) {
                        window.ContentAiBulkUi.setStep("setup");
                    }
                } catch (_) {}
                return;
            }
            if (data.state === "ERROR") {
                appendBulkLog(`Lỗi: ${data.error || data.message || "unknown"}`);
                stopBulkPoll();
                try {
                    localStorage.setItem(BULK_LAST_JOB_KEY(), jid);
                    localStorage.removeItem(BULK_JOB_STORAGE_KEY());
                } catch (_) {}
                scheduleSaveBulkState();
            }
        } catch (e) {
            appendBulkLog(String(e.message || e));
        }
    };
    const startBulkPoll = (jobId) => {
        stopBulkPoll();
        const stopBtn = byId("btnBulkWriteStopPoll");
        if (stopBtn) stopBtn.hidden = false;
        const stopBar = byId("btnBulkV2StopWrite");
        if (stopBar) {
            stopBar.disabled = false;
            stopBar.classList.remove("is-busy");
        }
        pollBulkJob(jobId);
        _bulkPollTimer = setInterval(() => pollBulkJob(jobId), 2200);
    };
    if (btnBulkAddKeyword) {
        btnBulkAddKeyword.addEventListener("click", () => void addBulkKeywordFromInput());
    }
    if (btnBulkExpandAll) {
        btnBulkExpandAll.addEventListener("click", () => setAllBulkDetailsOpen(true));
    }
    if (btnBulkCollapseAll) {
        btnBulkCollapseAll.addEventListener("click", () => setAllBulkDetailsOpen(false));
    }
    if (bulkAddKeywordInput) {
        bulkAddKeywordInput.addEventListener("keydown", (ev) => {
            if (ev.key === "Enter" && (ev.ctrlKey || ev.metaKey)) {
                ev.preventDefault();
                void addBulkKeywordFromInput();
            }
        });
    }
    if (btnBulkImportText) {
        btnBulkImportText.addEventListener("click", () => void importBulkTextToList());
    }
    if (btnBulkImportFile) {
        btnBulkImportFile.addEventListener("click", async () => {
            const f = bulkImportFile && bulkImportFile.files && bulkImportFile.files[0];
            if (!f) {
                if (bulkImportFileHint) bulkImportFileHint.textContent = "Chọn file .xlsx, .txt hoặc .csv trước.";
                return;
            }
            await importBulkUploadFile(f);
            if (bulkImportFile) bulkImportFile.value = "";
        });
    }
    if (bulkImportFile) {
        bulkImportFile.addEventListener("change", () => {
            if (bulkImportFileHint) bulkImportFileHint.textContent = "";
        });
    }
    if (bulkKeywordsFile) {
        bulkKeywordsFile.addEventListener("change", async () => {
            const f = bulkKeywordsFile.files && bulkKeywordsFile.files[0];
            if (!f) return;
            const name = String(f.name || "").toLowerCase();
            if (name.endsWith(".xlsx")) {
                await importBulkUploadFile(f);
            } else {
                const text = await f.text();
                if (bulkKeywordsText) {
                    const cur = bulkKeywordsText.value.trim();
                    bulkKeywordsText.value = cur ? `${cur}\n${text}` : text;
                }
                await importBulkTextToList();
            }
            bulkKeywordsFile.value = "";
        });
    }
    const saveBulkSetupToProjects = async () => {
        const bulkItems = mergeBulkItems();
        if (!bulkItems.length) {
            appendBulkLog("Chưa có từ khóa để lưu nháp.");
            return false;
        }
        const twEl = byId("bulkTargetWebsite");
        const target_website = twEl ? twEl.value.trim() : "";
        if (!target_website) {
            appendBulkLog("Cần Target website để lưu nháp theo domain.");
            if (msg) msg.textContent = "Nhập Target website trước khi lưu nháp.";
            return false;
        }
        const keywords = bulkItems.map((x) => x.keyword);
        try {
            const res = await fetch("/content-ai/bulk-setup/save", {
                method: "POST",
                headers: authJsonHeaders(),
                body: JSON.stringify({ keywords, items: bulkItems, target_website, brand_name }),
            });
            const data = await res.json().catch(() => ({}));
            if (!res.ok) {
                throw new Error((data && data.detail) ? String(data.detail) : `Lỗi HTTP ${res.status}`);
            }
            const n = Number(data.saved) || 0;
            appendBulkLog(`Đã lưu ${n} bài nháp (setup, chưa content) — xem tab Lưu nháp trong Bài viết site.`);
            if (msg) msg.textContent = `Đã lưu ${n} bài nháp cho ${normalizeTargetBase(target_website) || target_website}.`;
            await refreshProjects(false);
            return true;
        } catch (e) {
            appendBulkLog(`Lưu nháp lỗi: ${String(e.message || e)}`);
            if (msg) msg.textContent = String(e.message || e);
            return false;
        }
    };
    const btnBulkSaveSetup = byId("btnBulkSaveSetup");
    if (btnBulkSaveSetup) {
        btnBulkSaveSetup.addEventListener("click", async () => {
            btnBulkSaveSetup.disabled = true;
            try {
                await saveBulkSetupToProjects();
            } finally {
                btnBulkSaveSetup.disabled = false;
            }
        });
    }
    const bulkWriteModeBackdropEl = byId("bulkWriteModeBackdrop");
    const bulkWriteModeModalEl = byId("bulkWriteModeModal");
    const bulkWriteModeAllEl = byId("bulkWriteModeAll");
    const bulkWriteModeSelectedEl = byId("bulkWriteModeSelected") || byId("bulkWriteModeSetup");
    let _bulkWriteModeResolve = null;
    const closeBulkWriteModeModal = (mode) => {
        if (bulkWriteModeBackdropEl) bulkWriteModeBackdropEl.classList.remove("open");
        if (bulkWriteModeModalEl) {
            bulkWriteModeModalEl.classList.remove("open");
            bulkWriteModeModalEl.setAttribute("aria-hidden", "true");
        }
        if (_bulkWriteModeResolve) {
            _bulkWriteModeResolve(mode);
            _bulkWriteModeResolve = null;
        }
    };
    const countBulkUiSelected = () => {
        try {
            if (window.ContentAiBulkUi && typeof window.ContentAiBulkUi.getSelectedKeywords === "function") {
                return (window.ContentAiBulkUi.getSelectedKeywords() || []).length;
            }
        } catch (_) {}
        return 0;
    };
    const openBulkWriteModeModal = (preferredMode) => {
        const all = mergeBulkItems();
        if (!all.length) return Promise.resolve(null);
        return new Promise((resolve) => {
            _bulkWriteModeResolve = resolve;
            const hasSelected = countBulkUiSelected() > 0;
            const preferSelected = preferredMode === "selected" || (preferredMode !== "all" && hasSelected);
            if (bulkWriteModeAllEl) bulkWriteModeAllEl.checked = !preferSelected;
            if (bulkWriteModeSelectedEl) bulkWriteModeSelectedEl.checked = !!preferSelected;
            if (bulkWriteModeBackdropEl) bulkWriteModeBackdropEl.classList.add("open");
            if (bulkWriteModeModalEl) {
                bulkWriteModeModalEl.classList.add("open");
                bulkWriteModeModalEl.setAttribute("aria-hidden", "false");
            }
        });
    };
    if (bulkWriteModeAllEl && bulkWriteModeSelectedEl) {
        const syncBulkWriteModeChecks = (picked) => {
            if (picked === "all") {
                bulkWriteModeAllEl.checked = true;
                bulkWriteModeSelectedEl.checked = false;
            } else {
                bulkWriteModeAllEl.checked = false;
                bulkWriteModeSelectedEl.checked = true;
            }
        };
        bulkWriteModeAllEl.addEventListener("change", () => {
            if (bulkWriteModeAllEl.checked) syncBulkWriteModeChecks("all");
            else if (!bulkWriteModeSelectedEl.checked) bulkWriteModeAllEl.checked = true;
        });
        bulkWriteModeSelectedEl.addEventListener("change", () => {
            if (bulkWriteModeSelectedEl.checked) syncBulkWriteModeChecks("selected");
            else if (!bulkWriteModeAllEl.checked) bulkWriteModeAllEl.checked = true;
        });
    }
    const btnBulkWriteModeCancel = byId("btnBulkWriteModeCancel");
    if (btnBulkWriteModeCancel) btnBulkWriteModeCancel.addEventListener("click", () => closeBulkWriteModeModal(null));
    const btnBulkWriteModeOk = byId("btnBulkWriteModeOk");
    if (btnBulkWriteModeOk) {
        btnBulkWriteModeOk.addEventListener("click", () => {
            const selectedOnly = bulkWriteModeSelectedEl && bulkWriteModeSelectedEl.checked;
            const mode = selectedOnly ? "selected" : "all";
            const filtered = filterBulkItemsByWriteMode(mergeBulkItems(), mode);
            if (!filtered.length) {
                appendBulkLog(
                    mode === "selected"
                        ? "Chưa tích chọn bài nào trong bảng. Hãy tích checkbox các bài cần viết."
                        : "Chưa có từ khóa."
                );
                return;
            }
            closeBulkWriteModeModal(mode);
        });
    }
    if (bulkWriteModeBackdropEl) {
        bulkWriteModeBackdropEl.addEventListener("click", (ev) => {
            if (ev.target === bulkWriteModeBackdropEl) closeBulkWriteModeModal(null);
        });
    }
    document.addEventListener("keydown", (ev) => {
        if (ev.key !== "Escape") return;
        if (bulkWriteModeModalEl && bulkWriteModeModalEl.classList.contains("open")) {
            closeBulkWriteModeModal(null);
        }
    });
    const startBulkWriteJob = async (writeMode) => {
        const mode = writeMode === "selected" || writeMode === "setup" ? "selected" : "all";
        let bulkItems = filterBulkItemsByWriteMode(mergeBulkItems(), mode);
        if (!bulkItems.length) {
            appendBulkLog(
                mode === "selected"
                    ? "Chưa tích chọn bài nào trong bảng. Hãy tích checkbox các bài cần viết."
                    : "Chưa có từ khóa."
            );
            return;
        }
        const keywords = bulkItems.map((x) => x.keyword);
        const twEl = byId("bulkTargetWebsite");
        const bnEl = byId("bulkBrandName");
        const target_website = twEl ? twEl.value.trim() : "";
        const brand_name = bnEl ? bnEl.value.trim() : "";
        const target_word_count = 1000;
        const modeLabel = mode === "selected" ? "đã chọn" : "tất cả";
        if (window.DigiSeoConfirmCredit) {
            const ok = await window.DigiSeoConfirmCredit({
                module: "content_ai",
                action: "article_short",
                quantity: keywords.length,
                wordCount: target_word_count,
                quotaKey: "ai_articles",
                label: "Content AI — viết hàng loạt (" + keywords.length + " bài)",
            });
            if (!ok) return;
        }
        appendBulkLog(`Gửi job ${keywords.length} từ khóa (${modeLabel}) lên server…`);
        const res = await fetch("/content-ai/bulk-jobs/start", {
            method: "POST",
            headers: authJsonHeaders(),
            body: JSON.stringify({
                keywords,
                items: bulkItems,
                target_website,
                target_word_count,
                secondary_keywords: [],
                brand_name,
                wp_category_id: null,
            }),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
            if (window.ContentAiUsage && window.ContentAiUsage.handleQuotaResponse(res, data)) {
                throw new Error("Đã hết quota — vui lòng nâng cấp gói.");
            }
            let errMsg = (data && data.detail) ? String(data.detail) : `Lỗi HTTP ${res.status}`;
            if (typeof data.detail === "object" && data.detail && data.detail.message) {
                errMsg = String(data.detail.message);
            }
            if (res.status === 409 && typeof data.detail === "object" && data.detail) {
                errMsg = String(data.detail.message || errMsg);
                const rejected = Array.isArray(data.detail.rejected) ? data.detail.rejected : [];
                rejected.forEach((r) => {
                    const existing = window.ContentAiDuplicate
                        ? window.ContentAiDuplicate.formatExisting(r.existing)
                        : "";
                    appendBulkLog(
                        existing
                            ? `Trùng: "${r.keyword}" — ${r.message || ""} (${existing})`
                            : `Trùng: "${r.keyword}" — ${r.message || ""}`
                    );
                });
                if (
                    rejected.length
                    && window.ContentAiDuplicate
                    && typeof window.ContentAiDuplicate.renderBulkWarning === "function"
                ) {
                    window.ContentAiDuplicate.renderBulkWarning(
                        rejected.map((r) => ({ keyword: r.keyword, duplicate: r }))
                    );
                }
            }
            if (res.status === 404) {
                errMsg =
                    "API viết hàng loạt chưa có trên server (404). Tắt cửa sổ run.bat/uvicorn cũ, chạy lại run.bat, rồi Ctrl+F5 trang này.";
            }
            throw new Error(errMsg);
        }
        if (window.ContentAiUsage && window.ContentAiUsage.refresh) void window.ContentAiUsage.refresh();
        appendBulkLog(data.note || `Job ${data.job_id} đã xếp hàng (${modeLabel}, ${keywords.length} bài).`);
        if (Array.isArray(data.rejected_duplicates) && data.rejected_duplicates.length) {
            data.rejected_duplicates.forEach((r) => {
                const existing = window.ContentAiDuplicate
                    ? window.ContentAiDuplicate.formatExisting(r.existing)
                    : "";
                appendBulkLog(
                    existing
                        ? `Đã bỏ trùng: "${r.keyword}" — ${r.message || ""} (${existing})`
                        : `Đã bỏ trùng: "${r.keyword}" — ${r.message || ""}`
                );
            });
            if (window.ContentAiDuplicate && typeof window.ContentAiDuplicate.renderBulkWarning === "function") {
                window.ContentAiDuplicate.renderBulkWarning(
                    data.rejected_duplicates.map((r) => ({ keyword: r.keyword, duplicate: r }))
                );
            }
        }
        const jobKeywords = Array.isArray(data.rejected_duplicates) && data.rejected_duplicates.length
            ? keywords.filter((k) => {
                const lk = String(k || "").trim().toLowerCase();
                return !(data.rejected_duplicates || []).some(
                    (r) => String(r.keyword || "").trim().toLowerCase() === lk
                );
            })
            : keywords;
        initBulkJobStatusTable(jobKeywords);
        if (bulkJobProgress) bulkJobProgress.hidden = false;
        if (bulkJobProgressFill) bulkJobProgressFill.style.width = "1%";
        if (bulkJobPct) bulkJobPct.textContent = "0%";
        if (bulkJobStatus) bulkJobStatus.textContent = "Đã xếp hàng — chờ server viết bài…";
        try {
            localStorage.setItem(BULK_JOB_STORAGE_KEY(), data.job_id);
        } catch (_) {}
        startBulkPoll(data.job_id);
    };
    // Expose for bulk board "Viết bài đã chọn" (avoid racey row-swap hack).
    window.__contentAiStartBulkWriteJob = startBulkWriteJob;
    window.__contentAiOpenBulkWriteModeModal = openBulkWriteModeModal;
    const btnBulkWriteStart = byId("btnBulkWriteStart");
    if (btnBulkWriteStart) {
        btnBulkWriteStart.addEventListener("click", async () => {
            const bulkItems = mergeBulkItems();
            if (!bulkItems.length) {
                appendBulkLog("Chưa có từ khóa.");
                return;
            }
            const writeMode = await openBulkWriteModeModal();
            if (!writeMode) return;
            btnBulkWriteStart.disabled = true;
            try {
                await startBulkWriteJob(writeMode);
            } catch (e) {
                appendBulkLog(String(e.message || e));
            } finally {
                btnBulkWriteStart.disabled = false;
            }
        });
    }
    const btnBulkWriteStopPoll = byId("btnBulkWriteStopPoll");
    if (btnBulkWriteStopPoll) {
        btnBulkWriteStopPoll.addEventListener("click", () => {
            void cancelBulkWriteJob();
        });
    }
    const btnBulkV2StopWrite = byId("btnBulkV2StopWrite");
    if (btnBulkV2StopWrite) {
        btnBulkV2StopWrite.addEventListener("click", () => {
            void cancelBulkWriteJob();
        });
    }

    const tabMainSingle = byId("tabMainSingle");
    const tabMainBulk = byId("tabMainBulk");
    if (tabMainSingle) {
        tabMainSingle.addEventListener("click", () => {
            setContentAiMainView("single");
        });
    }
    if (tabMainBulk) {
        tabMainBulk.addEventListener("click", () => {
            setContentAiMainView("bulk");
            const tw = byId("targetWebsite");
            const btw = byId("bulkTargetWebsite");
            if (tw && btw && !btw.value.trim()) btw.value = tw.value;
            renderBulkKeywordList();
            updateBulkKwCount();
        });
    }
    const tabMainAutoUpdate = byId("tabMainAutoUpdate");
    if (tabMainAutoUpdate) {
        tabMainAutoUpdate.addEventListener("click", () => {
            setContentAiMainView("autoupdate");
        });
    }
    const closeProjectView = () => {
        setContentAiMainView("single");
    };
    const btnCloseProjectSitesPanel = byId("btnCloseProjectSitesPanel");
    if (btnCloseProjectSitesPanel) btnCloseProjectSitesPanel.addEventListener("click", closeProjectView);
    document.querySelectorAll(".btn-close-project-view").forEach((btn) => {
        btn.addEventListener("click", closeProjectView);
    });
    updateBulkKwCount();

    const resolveSiteForAllArticles = () => {
        const fromFilter = String(_projectsSiteFilterBase || "").trim();
        if (fromFilter) return fromFilter;
        const wp = normalizeWpUrl(byId("wpUrl") && byId("wpUrl").value.trim());
        if (wp) return wp;
        const tg = normalizeTargetBase(byId("targetWebsite") && byId("targetWebsite").value.trim());
        if (tg) return tg;
        const sites = collectConnectedSites();
        if (sites.length) return sites[0].url;
        return "";
    };
    const openViewAllSiteArticles = async () => {
        const base = resolveSiteForAllArticles();
        if (!base) {
            if (msg) msg.textContent = "Chưa có website — thêm site đăng bài hoặc chọn một site trong danh sách.";
            return;
        }
        let hostLabel = base;
        try {
            hostLabel = new URL(base).host || base;
        } catch (_) {}
        _projectsSiteFilterBase = normalizeTargetBase(base) || normalizeWpUrl(base) || "";
        try {
            renderProjects();
            renderConnectedSitesPanel();
        } catch (_) {}
        await openSiteArticlesModal(_projectsSiteFilterBase, hostLabel, {
            resetFilter: true,
            clearSearch: true,
        });
    };
    const btnViewAllSiteArticles = byId("btnViewAllSiteArticles");
    if (btnViewAllSiteArticles) btnViewAllSiteArticles.addEventListener("click", () => void openViewAllSiteArticles());
    const btnViewAllProjects = byId("btnViewAllProjects");
    if (btnViewAllProjects) btnViewAllProjects.addEventListener("click", () => void openAllPublishingSitesModal());
    const btnAllArticlesClose = byId("btnAllArticlesClose");
    if (btnAllArticlesClose) btnAllArticlesClose.addEventListener("click", closeAllArticlesModal);
    if (allArticlesBackdropEl) {
        allArticlesBackdropEl.addEventListener("click", (ev) => {
            if (ev.target === allArticlesBackdropEl) closeAllArticlesModal();
        });
    }
    if (allArticlesSearchEl) {
        allArticlesSearchEl.addEventListener("input", () => {
            try {
                if (allArticlesModalEl && allArticlesModalEl.classList.contains("open")) {
                    renderAllPublishingSitesList();
                }
            } catch (_) {}
        });
    }
    const btnContentAiRecentPlus = byId("btnContentAiRecentPlus");
    if (btnContentAiRecentPlus) {
        btnContentAiRecentPlus.addEventListener("click", () => {
            setContentAiMainView("single");
            const pk = byId("primaryKeyword");
            window.setTimeout(() => {
                if (pk) pk.focus({ preventScroll: true });
            }, 350);
        });
    }
    const toggleAiAvailability = () => {
        const hasPrimary = !!byId("primaryKeyword").value.trim();
        aiButtons.forEach((btnItem) => {
            const field = btnItem.dataset.field;
            btnItem.disabled = field === "target_website" ? false : !hasPrimary;
        });
        if (!hasPrimary) {
            setHint("primary_keyword", "Hãy nhập từ khóa chính trước để kích hoạt toàn bộ gợi ý AI.");
            try {
                if (window.ContentAiDuplicate) window.ContentAiDuplicate.clearSingleUi();
            } catch (_) {}
        } else {
            const dupBlocked = !!(window.ContentAiDuplicate && window.ContentAiDuplicate.isBlocked());
            if (!dupBlocked) {
                setHint("primary_keyword", "Da kich hoat goi y AI theo tu khoa chinh.");
            }
            try {
                if (window.ContentAiDuplicate) window.ContentAiDuplicate.scheduleSingleCheck();
            } catch (_) {}
        }
    };

    const applySuggestion = (field, value) => {
        const mapping = {
            title: "title",
            target_website: "targetWebsite",
            slug: "slug",
            primary_keyword: "primaryKeyword",
            secondary_keywords: "secondaryKeywords",
            outline_content: "outlineContent",
            meta_description: "meta",
            tags: "tags",
            content: "content",
        };
        const id = mapping[field];
        if (!id) return;
        const input = byId(id);
        if (!input) return;
        input.value = value || "";
        if (field === "outline_content") {
            try {
                autoGrowOutline();
            } catch (_) {}
        }
        // removed "Lịch sử gợi ý AI" panel
    };

    aiButtons.forEach((button) => {
        button.addEventListener("click", async () => {
            const field = button.dataset.field;
            if (!field) return;
            const oldText = button.textContent;
            button.textContent = "Đang gợi ý...";
            button.disabled = true;
            setHint(field, "");
            try {
                const ctx = buildContext();
                let value = "";
                let detectedIntent = "";
                if (field === "title") {
                    const current = byId("title").value.trim();
                    const nextObj = await fetchSuggestion(field, ctx);
                    const next = nextObj.value || "";
                    detectedIntent = nextObj.detected_intent || detectedIntent;
                    value = next;
                    if (value && value !== current) lastSuggestedTitle = value;
                } else if (field === "slug") {
                    value = buildStrictSlug();
                    if (!value) {
                        const out = await fetchSuggestion(field, ctx);
                        value = out.value || "";
                        detectedIntent = out.detected_intent || "";
                    }
                } else if (field === "target_website") {
                    const seenTw = new Set();
                    const mergedTw = [];
                    const pushTw = (raw) => {
                        const b = normalizeTargetBase(raw) || normalizeWpUrl(raw);
                        if (!b) return;
                        const k = b.toLowerCase();
                        if (seenTw.has(k)) return;
                        seenTw.add(k);
                        mergedTw.push(b);
                    };
                    settingsPublishingSitesFlat.forEach((s) => pushTw(s.url));
                    readTargetHistory().forEach(pushTw);
                    if (mergedTw[0]) {
                        value = mergedTw[0];
                    } else {
                        const out = await fetchSuggestion(field, ctx);
                        value = out.value || "";
                        detectedIntent = out.detected_intent || "";
                    }
                } else {
                    const out = await fetchSuggestion(field, ctx);
                    value = out.value || "";
                    detectedIntent = out.detected_intent || "";
                }
                applySuggestion(field, value);
                setDetectedIntentDebug(detectedIntent);
                if (field === "target_website") {
                    rememberTargetWebsite(value);
                }
                setHint(field, "Da cap nhat goi y AI theo tu khoa chinh.");
            } catch (err) {
                const errText = String(err.message || err);
                setHint(field, errText);
            } finally {
                button.textContent = oldText;
                button.disabled = false;
                toggleAiAvailability();
            }
        });
    });
    const pkInputEl = byId("primaryKeyword");
    if (pkInputEl) {
        pkInputEl.addEventListener("input", () => {
            toggleAiAvailability();
            syncSlugFromPrimary(true);
        });
    }
    const targetWebsiteEl = byId("targetWebsite");
    if (targetWebsiteEl) {
        targetWebsiteEl.addEventListener("input", () => {
            syncSlugFromPrimary();
            try { scheduleSingleWpCategoriesLoad(); } catch (_) {}
        });
        targetWebsiteEl.addEventListener("change", () => {
            rememberTargetWebsite(targetWebsiteEl.value);
            try { scheduleSingleWpCategoriesLoad(); } catch (_) {}
        });
    }
    const checkDupBtn = byId("btnCheckDuplicate");
    if (checkDupBtn) {
        checkDupBtn.addEventListener("click", async () => {
            const pk = byId("primaryKeyword");
            const kw = pk ? pk.value.trim() : "";
            if (!kw) {
                try { if (typeof showCaToast === "function") showCaToast("Nhập từ khóa chính trước.", "warn"); } catch (_) {}
                return;
            }
            checkDupBtn.disabled = true;
            checkDupBtn.textContent = "⏳ Đang kiểm tra…";
            try {
                const result = await window.ContentAiDuplicate.runSingleCheck({ refresh: true, toast: true });
                if (!result) {
                    try { if (typeof showCaToast === "function") showCaToast("Không nhận được kết quả kiểm tra trùng.", "warn"); } catch (_) {}
                }
            } catch (err) {
                try { if (typeof showCaToast === "function") showCaToast(String(err && err.message || "Kiểm tra trùng thất bại."), "error"); } catch (_) {}
            }
            checkDupBtn.disabled = false;
            checkDupBtn.textContent = "🔍 Kiểm tra trùng";
        });
    }
    toggleAiAvailability();
    syncSlugFromPrimary(true);
    renderUploadList();
    renderTargetHistory();
    renderWpUrlHistory();
    renderWpUserHistory();
    const CLUSTER_PREFILL_KEY = "seoauto_content_ai_prefill";
    const CLUSTER_PREFILL_LEGACY_KEYS = ["seoauto_cluster_bulk_prefill", "seoauto_cluster_single_prefill"];
    const CLUSTER_PREFILL_TOAST = "Đã nhập đầy đủ từ khóa và outline từ cụm keyword";
    const clearClusterPrefillStorage = () => {
        try {
            sessionStorage.removeItem(CLUSTER_PREFILL_KEY);
            CLUSTER_PREFILL_LEGACY_KEYS.forEach((k) => sessionStorage.removeItem(k));
        } catch (_) {}
    };
    const keywordTextFromToken = (k) => {
        if (k == null) return "";
        if (typeof k === "string") return k.trim();
        if (typeof k === "object") return String(k.keyword || k.text || "").trim();
        return String(k).trim();
    };
    const collectSecondaryFromPayload = (p, mainKw) => {
        const mainLower = String(mainKw || "").trim().toLowerCase();
        const buckets = [];
        const addList = (list) => {
            if (!list) return;
            buckets.push(Array.isArray(list) ? list : [list]);
        };
        addList(p.secondary_keywords);
        addList(p.supporting_keywords);
        addList(p.keywords);
        addList(p.variations);
        addList(p.semantic_keywords);
        const seen = new Set();
        const out = [];
        buckets.forEach((list) => {
            (list || []).forEach((item) => {
                const k = keywordTextFromToken(item);
                if (!k) return;
                const lk = k.toLowerCase();
                if (lk === mainLower || seen.has(lk)) return;
                seen.add(lk);
                out.push(k);
            });
        });
        return out;
    };
    const isRawJsonOutlineText = (s) => {
        const t = String(s || "").trim();
        if (!t) return false;
        const first = t.charAt(0);
        const last = t.charAt(t.length - 1);
        if ((first === "{" && last === "}") || (first === "[" && last === "]")) {
            try {
                JSON.parse(t);
                return true;
            } catch (_) {}
        }
        return false;
    };
    const generateSeoOutlineFromPayload = (p, mainKw, secKws) => {
        const title = String(p.recommended_title || p.topic || mainKw || "").trim();
        const mk = String(mainKw || p.topic || "").trim();
        const intent = String(p.intent || "").trim();
        const contentType = String(p.content_type || p.suggested_content_type || "").trim();
        const lines = [`H1: ${title}`, ""];
        if (mk) lines.push(`H2: ${mk} là gì?`);
        if (secKws.length) {
            lines.push(`H2: ${contentType ? `${contentType} — ` : "Chi tiết về "}${mk}`);
            secKws.slice(0, 6).forEach((kw) => lines.push(`  H3: ${kw}`));
        }
        lines.push("H2: Lợi ích và ứng dụng");
        if (secKws.length > 6) {
            lines.push("H2: Câu hỏi thường gặp");
            secKws.slice(6, 10).forEach((kw) => lines.push(`  - ${kw}`));
        }
        lines.push("H2: Kết luận");
        const meta = [];
        if (intent) meta.push(`Intent: ${intent}`);
        if (contentType) meta.push(`Loại bài: ${contentType}`);
        if (meta.length) {
            lines.push("");
            lines.push(meta.join(" · "));
        }
        return lines.join("\n").trim();
    };
    const resolveOutlineFromPayload = (p, mainKw, secKws) => {
        const candidates = [p.custom_outline, p.outline, p.content_angle].filter(Boolean);
        for (const raw of candidates) {
            const s = String(raw).trim();
            if (s && !isRawJsonOutlineText(s)) return s;
        }
        return generateSeoOutlineFromPayload(p, mainKw, secKws);
    };
    const readClusterPrefillPayload = () => {
        try {
            let raw = sessionStorage.getItem(CLUSTER_PREFILL_KEY);
            if (raw) {
                sessionStorage.removeItem(CLUSTER_PREFILL_KEY);
                return JSON.parse(raw);
            }
            raw = sessionStorage.getItem("seoauto_cluster_bulk_prefill");
            if (raw) {
                sessionStorage.removeItem("seoauto_cluster_bulk_prefill");
                const bulk = JSON.parse(raw);
                return { mode: "bulk", ...bulk };
            }
            raw = sessionStorage.getItem("seoauto_cluster_single_prefill");
            if (raw) {
                sessionStorage.removeItem("seoauto_cluster_single_prefill");
                return { mode: "single", data: JSON.parse(raw) };
            }
        } catch (_) {}
        return null;
    };
    const applySingleClusterPrefill = (p) => {
        const mainKw = keywordTextFromToken(p.primary_keyword || p.main_keyword || "");
        const pk = byId("primaryKeyword");
        if (pk) pk.value = mainKw;
        const secKws = collectSecondaryFromPayload(p, mainKw);
        const sk = byId("secondaryKeywords");
        if (sk) sk.value = secKws.join(", ");
        const ti = byId("title");
        const topicTitle = String(p.recommended_title || p.topic || "").trim();
        if (ti && topicTitle) ti.value = topicTitle;
        const mt = byId("meta");
        if (mt && p.meta_description) mt.value = String(p.meta_description);
        const tw = byId("targetWebsite");
        if (tw && p.target_website) tw.value = String(p.target_website);
        const twc = byId("targetWordCount");
        if (twc && p.target_word_count != null && String(p.target_word_count).trim() !== "") {
            twc.value = String(p.target_word_count);
        }
        const ol = byId("outlineContent");
        if (ol) ol.value = resolveOutlineFromPayload(p, mainKw, secKws);
        if (p.intent) setDetectedIntentDebug(p.intent);
        syncSlugFromPrimary(true);
        toggleAiAvailability();
        try {
            autoGrowOutline();
        } catch (_) {}
    };
    const applyClusterPrefillFromSession = async () => {
        let appliedMode = false;
        try {
            const payload = readClusterPrefillPayload();
            if (payload && payload.mode === "bulk" && Array.isArray(payload.items) && payload.items.length) {
                resetBulkWriteForm();
                setContentAiMainView("bulk");
                const btw = byId("bulkTargetWebsite");
                if (btw && payload.target_website) btw.value = payload.target_website;
                const parsed = payload.items.map((it) => {
                    const main = keywordTextFromToken(it.keyword || it.primary_keyword || it.main_keyword || "");
                    const secKws = collectSecondaryFromPayload(it, main);
                    const outlineRaw = String(it.custom_outline || it.outline || "").trim();
                    const outline = outlineRaw && !isRawJsonOutlineText(outlineRaw)
                        ? outlineRaw
                        : generateSeoOutlineFromPayload(it, main, secKws);
                    const intent = String(it.intent || "").trim();
                    return {
                        keyword: main,
                        custom_title: String(it.custom_title || it.topic || "").trim(),
                        custom_description: String(it.custom_description || it.meta_description || (intent ? `Search intent: ${intent}` : "")).trim(),
                        custom_outline: outline,
                        search_volume: it.search_volume != null && it.search_volume !== "" ? it.search_volume : "",
                        content_type: String(it.content_type || it.suggested_content_type || "").trim(),
                        target_word_count: it.target_word_count != null && it.target_word_count !== "" ? it.target_word_count : "",
                        secondary_keywords: secKws.length ? secKws.join(", ") : (
                            Array.isArray(it.secondary_keywords)
                                ? it.secondary_keywords.map((x) => keywordTextFromToken(x)).filter(Boolean).join(", ")
                                : String(it.secondary_keywords || "").trim()
                        ),
                    };
                }).filter((x) => x.keyword);
                if (parsed.length) {
                    await addBulkKeywordsFromParsed(parsed, { fetchVolume: false });
                    bulkKeywordRows.forEach((row) => {
                        if (row.custom_title || row.custom_description || row.custom_outline || row.secondary_keywords) {
                            row.detailsOpen = true;
                        }
                    });
                    renderBulkKeywordList();
                }
                scheduleSaveBulkState();
                appliedMode = "bulk";
            } else if (payload && payload.mode === "single" && payload.data && typeof payload.data === "object") {
                resetContentAiSingleForm();
                setContentAiMainView("single");
                applySingleClusterPrefill(payload.data);
                scheduleSaveFormState();
                appliedMode = "single";
            } else {
                const params = new URLSearchParams(window.location.search || "");
                const modeParam = params.get("mode");
                const wantBulk = modeParam === "bulk" || params.get("view") === "bulk";
                if (wantBulk) setContentAiMainView("bulk");
                else if (modeParam === "single") setContentAiMainView("single");
            }
        } catch (_) {}
        clearClusterPrefillStorage();
        return appliedMode;
    };
    window.addEventListener("digiseo:content-ai-prefill", function () {
        void (async () => {
            try {
                setContentAiMainView("single");
            } catch (_) {}
            const applied = await applyClusterPrefillFromSession();
            if (applied) {
                try {
                    const host = byId("caToastHost");
                    if (host) {
                        const el = document.createElement("div");
                        el.className = "ca-toast success";
                        el.textContent = CLUSTER_PREFILL_TOAST;
                        host.appendChild(el);
                        window.setTimeout(() => {
                            el.style.opacity = "0";
                            el.style.transition = "opacity 0.25s";
                            window.setTimeout(() => el.remove(), 280);
                        }, 3200);
                    }
                } catch (_) {}
            }
        })();
    });
    void (async () => {
        const prefillMode = await applyClusterPrefillFromSession();
        if (prefillMode) {
            try {
                const host = byId("caToastHost");
                if (host) {
                    const el = document.createElement("div");
                    el.className = "ca-toast success";
                    el.textContent = CLUSTER_PREFILL_TOAST;
                    host.appendChild(el);
                    window.setTimeout(() => {
                        el.style.opacity = "0";
                        el.style.transition = "opacity 0.25s";
                        window.setTimeout(() => el.remove(), 280);
                    }, 3200);
                }
            } catch (_) {}
            try {
                await refreshProjects(true);
            } catch (_) {}
            return;
        }

        const params = new URLSearchParams(window.location.search || "");
        const articleIdFromUrl = String(params.get("article_id") || "").trim();

        if (articleIdFromUrl) {
            setContentAiMainView("single");
            try {
                await refreshProjects(false);
                await loadProjectIntoWriteTab(articleIdFromUrl);
                try {
                    const u = new URL(window.location.href);
                    u.searchParams.delete("article_id");
                    const qs = u.searchParams.toString();
                    window.history.replaceState({}, "", u.pathname + (qs ? "?" + qs : "") + u.hash);
                } catch (_) {}
            } catch (e) {
                try {
                    msg.textContent = "Không tải được bài viết từ chatbot: " + String(e.message || e);
                } catch (_) {}
            }
            try {
                await refreshProjects(false);
            } catch (_) {}
            return;
        }

        const restored = restoreFormState();
        restoreBulkState();
        try {
            const modeParam = params.get("mode");
            const viewParam = params.get("view");
            const savedJob = localStorage.getItem(BULK_JOB_STORAGE_KEY());
            const lastJob = localStorage.getItem(BULK_LAST_JOB_KEY()) || "";
            const savedView = getSavedBulkMainView();
            if (savedJob) {
                setContentAiMainView("bulk");
                startBulkPoll(savedJob);
            } else if (modeParam === "bulk" || viewParam === "bulk") {
                setContentAiMainView("bulk");
            } else if (modeParam === "autoupdate" || viewParam === "autoupdate") {
                setContentAiMainView("autoupdate");
            } else if (modeParam === "projects" || viewParam === "projects") {
                setContentAiMainView("projects");
            } else if (modeParam === "single") {
                setContentAiMainView("single");
            } else if (savedView) {
                setContentAiMainView(savedView);
            } else {
                setContentAiMainView("single");
            }
            // Re-fetch completed job once so F5 still shows written status.
            if (!savedJob && lastJob) {
                try {
                    const res = await fetch(`/content-ai/bulk-jobs/${encodeURIComponent(lastJob)}?ts=${Date.now()}`, {
                        headers: authHeaders(),
                    });
                    const data = await res.json().catch(() => ({}));
                    if (res.status === 404) {
                        try {
                            localStorage.removeItem(BULK_LAST_JOB_KEY());
                            localStorage.removeItem(BULK_JOB_STORAGE_KEY());
                        } catch (_) {}
                    } else if (res.ok && data && data.result && Array.isArray(data.result.items) && data.result.items.length) {
                        renderBulkJobItems(data.result.items, { mode: "merge" });
                        if (data.state === "SUCCESS" || data.state === "ERROR") {
                            setContentAiMainView("bulk");
                        }
                    }
                } catch (_) {}
            }
        } catch (_) {
            const savedView = getSavedBulkMainView();
            setContentAiMainView(savedView || "single");
        }
        try {
            await refreshProjects(!restored);
        } catch (_) {}
        try {
            hydrateBulkStatusFromProjects();
        } catch (_) {}
        try {
            refreshPreview();
        } catch (_) {}
        try {
            syncPreviewFallback();
        } catch (_) {}
    })();
    ["bulkTargetWebsite", "bulkBrandName", "bulkQuickInput", "bulkKeywordsText", "bulkAddKeywordInput"].forEach((id) => {
        const el = byId(id);
        if (el) {
            el.addEventListener("input", scheduleSaveBulkState);
            el.addEventListener("change", scheduleSaveBulkState);
        }
    });
    window.addEventListener("beforeunload", saveBulkState);
    renderConnectedSitesPanel();
    try {
        refreshPreview();
    } catch (_) {}
    // Initialize rich editor after restoring state so it picks up existing content.
    void initRichEditor();
    // Keep outline textarea expanded to always show full outline.
    try {
        const outlineEl = byId("outlineContent");
        if (outlineEl) outlineEl.addEventListener("input", autoGrowOutline);
        autoGrowOutline();
    } catch (_) {}
    purgeLegacySharedStorage();
    allProjects = [];
    settingsPublishingSitesFlat = [];
    try { schedulePublishChecklist(); } catch (_) {}
    void fetchSettingsPublishingSites().then(() => {
        renderTargetHistory();
        renderWpUrlHistory();
        renderConnectedSitesPanel();
    });
    document.addEventListener("visibilitychange", () => {
        if (document.visibilityState !== "visible") return;
        void fetchSettingsPublishingSites().then(() => {
            renderTargetHistory();
            renderWpUrlHistory();
            renderConnectedSitesPanel();
        });
    });
    document.querySelectorAll("input, textarea").forEach((el) => {
        if (el.type === "file") return;
        if (el.id === "content") return;
        el.addEventListener("input", scheduleSaveFormState);
        el.addEventListener("change", scheduleSaveFormState);
    });
    window.addEventListener("beforeunload", () => {
        if (_saveFormStateTimer) {
            window.clearTimeout(_saveFormStateTimer);
            _saveFormStateTimer = null;
        }
        flushSaveFormState();
    });

    if (btnUploadImage) btnUploadImage.addEventListener("click", async () => {
        const files = byId("imageUpload").files;
        if (!files || !files.length) {
            setHint("image", "Vui lòng chọn hình ảnh trước khi tải lên.");
            return;
        }
        setHint("image", "Đang tải hình ảnh...");
        btnUploadImage.disabled = true;
        try {
            for (const file of files) {
                const formData = new FormData();
                formData.append("file", file);
                const res = await fetch(`/content-ai/upload-image?ts=${Date.now()}`, {
                    method: "POST",
                    body: formData,
                });
                const data = await res.json().catch(() => ({}));
                if (!res.ok) throw new Error((data && data.detail) ? data.detail : "Upload failed");
                if (data.url) {
                    uploadedImages.push(data.url);
                    // Auto-insert into content immediately (no extra step).
                    try { insertImageIntoEditor(data.url); } catch (_) {}
                }
            }
            renderUploadList();
            setHint("image", "Đã tải ảnh và chèn vào Content.");
            saveFormState();
        } catch (e) {
            setHint("image", String(e.message || e));
        } finally {
            btnUploadImage.disabled = false;
            byId("imageUpload").value = "";
        }
    });

    if (btnOutlineReference) btnOutlineReference.addEventListener("click", async () => {
        const competitorUrl = byId("competitorUrl").value.trim();
        if (!competitorUrl) {
            setHint("competitor", "Vui lòng dán link đối thủ trước.");
            return;
        }
        btnOutlineReference.disabled = true;
        setHint("competitor", "Đang phân tích outline đối thủ...");
        try {
            const res = await fetch(`/content-ai/outline-reference?ts=${Date.now()}`, {
                method: "POST",
                headers: authJsonHeaders(),
                body: JSON.stringify({ competitor_url: competitorUrl }),
            });
            let data = await res.json().catch(() => ({}));
            if (!res.ok) throw new Error((data && data.detail) ? data.detail : "Không lấy được outline đối thủ.");
            if (window.SeoautoAwaitQueued && data.job_id && data.poll_url) {
                data = await window.SeoautoAwaitQueued(data, { headers: authJsonHeaders() });
            }
            const current = byId("outlineContent").value.trim();
            byId("outlineContent").value = (data.outline || "").trim();
            autoGrowOutline();
            setHint("competitor", `Đã lấy ${data.count || 0} heading từ bài đối thủ.`);
            if (!current && data.outline) {
                msg.textContent = "Đã điền outline tham khảo từ link đối thủ.";
            }
            saveFormState();
        } catch (e) {
            const raw = String(e.message || e);
            if (/not found/i.test(raw)) {
                setHint("competitor", "Không tìm thấy endpoint hoặc outline. Hãy refresh trang và thử lại URL đối thủ.");
            } else {
                setHint("competitor", raw);
            }
        } finally {
            btnOutlineReference.disabled = false;
        }
    });

    const runGoogleImageSearch = async () => {
        const q = (googleImageQuery ? googleImageQuery.value : "").trim() || byId("primaryKeyword").value.trim();
        if (!q) {
            setHint("google-images", "Vui lòng nhập từ khóa để tìm ảnh.");
            return;
        }
        const num = parseInt((googleImageNum && googleImageNum.value) ? googleImageNum.value : "8", 10) || 8;
        setHint("google-images", "Đang tìm ảnh Google...");
        if (btnGoogleImageSearch) btnGoogleImageSearch.disabled = true;
        try {
            const res = await fetch(`/content-ai/google-images/search?q=${encodeURIComponent(q)}&num=${encodeURIComponent(String(num))}&ts=${Date.now()}`, {
                headers: authJsonHeaders(),
            });
            let data = await res.json().catch(() => ({}));
            if (!res.ok) throw new Error((data && data.detail) ? data.detail : "Tìm ảnh thất bại (kiểm tra GOOGLE_API_KEY + GOOGLE_CSE_ID).");
            if (window.SeoautoAwaitQueued && data.job_id && data.poll_url) {
                data = await window.SeoautoAwaitQueued(data, { headers: authJsonHeaders() });
            }
            renderGoogleImageResults(data.items || []);
            setHint("google-images", `Đã tìm thấy ${(data.items || []).length} ảnh.`);
            saveFormState();
        } catch (e) {
            setHint("google-images", String(e.message || e));
        } finally {
            if (btnGoogleImageSearch) btnGoogleImageSearch.disabled = false;
        }
    };

    if (btnGoogleImageSearch) btnGoogleImageSearch.addEventListener("click", runGoogleImageSearch);
    if (googleImageQuery) {
        googleImageQuery.addEventListener("keydown", (e) => {
            if (e.key === "Enter") {
                e.preventDefault();
                runGoogleImageSearch();
            }
        });
    }

    if (btnReplaceAll) btnReplaceAll.addEventListener("click", () => {
        const from = byId("replaceFrom").value.trim();
        const to = byId("replaceTo").value.trim();
        const outline = byId("outlineContent").value;
        if (!outline.trim()) {
            setHint("outline-actions", "Vui lòng có outline trước khi Replace All.");
            return;
        }
        if (!from) {
            setHint("outline-actions", "Vui lòng nhập từ cần thay.");
            return;
        }
        const escaped = from.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
        const rgx = new RegExp(escaped, "gi");
        const count = (outline.match(rgx) || []).length;
        byId("outlineContent").value = outline.replace(rgx, to);
        setHint("outline-actions", `Đã thay ${count} vị trí.`);
        autoGrowOutline();
        saveFormState();
    });

    if (btnRefreshOutline) btnRefreshOutline.addEventListener("click", async () => {
        const outline = byId("outlineContent").value.trim();
        if (!outline) {
            setHint("outline-actions", "Vui lòng nhập outline trước khi làm mới.");
            return;
        }
        btnRefreshOutline.disabled = true;
        setHint("outline-actions", "Đang làm mới outline...");
        try {
            const res = await fetch(`/content-ai/outline-refresh?ts=${Date.now()}`, {
                method: "POST",
                headers: authJsonHeaders(),
                body: JSON.stringify({ outline }),
            });
            const data = await res.json().catch(() => ({}));
            if (!res.ok) throw new Error((data && data.detail) ? data.detail : "Làm mới outline thất bại.");
            if (data.outline) byId("outlineContent").value = data.outline;
            autoGrowOutline();
            setHint("outline-actions", "Đã làm mới outline bằng từ đồng nghĩa.");
            saveFormState();
        } catch (e) {
            setHint("outline-actions", String(e.message || e));
        } finally {
            btnRefreshOutline.disabled = false;
        }
    });

    if (btnCreateContent) btnCreateContent.addEventListener("click", async () => {
        const primaryKeyword = byId("primaryKeyword").value.trim();
        if (!primaryKeyword) {
            msg.textContent = "Cần nhập từ khóa chính trước.";
            return;
        }
        if (btnCreateContent.disabled) return;
        try {
            if (window.ContentAiDuplicate) {
                const dup = await window.ContentAiDuplicate.runSingleCheck({ toast: false });
                if (dup && dup.is_duplicate) {
                    msg.textContent = String(dup.message || "Bài viết này đã tồn tại");
                    return;
                }
            }
        } catch (_) {}
        const writeSignal = _beginContentWriteSession();
        _setCreateContentButtonsBusy(true);
        _clearEditorWriteError();
        _showEditorWriteBar("Đang chuẩn bị viết bài…");
        msg.textContent = "";
        try {
            const ctx = buildContext();
            if (!byId("outlineContent").value.trim()) {
                _showEditorWriteBar("Đang tạo outline…");
                const outlineOut = await fetchSuggestion("outline_content", ctx, { signal: writeSignal, skipConfirm: true });
                if (outlineOut && outlineOut.value) {
                    byId("outlineContent").value = outlineOut.value;
                    autoGrowOutline();
                }
                if (outlineOut && outlineOut.detected_intent) {
                    setDetectedIntentDebug(outlineOut.detected_intent);
                }
            }

            const generated = await streamSuggestion("content", ctx, { signal: writeSignal });
            if (!String(generated || "").trim()) return;

            const postCtx = buildContext();
            const [titleOut, metaOut, slugOut] = await Promise.all([
                fetchSuggestion("title", postCtx, { skipConfirm: true }),
                fetchSuggestion("meta_description", postCtx, { skipConfirm: true }),
                fetchSuggestion("slug", postCtx, { skipConfirm: true }),
            ]);
            if (titleOut && titleOut.detected_intent) {
                setDetectedIntentDebug(titleOut.detected_intent);
            }
            if (titleOut && titleOut.value) {
                byId("title").value = _firstLine(titleOut.value);
            }
            if (metaOut && metaOut.detected_intent) {
                setDetectedIntentDebug(metaOut.detected_intent);
            }
            if (metaOut && metaOut.value) {
                byId("meta").value = _firstLine(metaOut.value);
            }
            if (slugOut && slugOut.detected_intent) {
                setDetectedIntentDebug(slugOut.detected_intent);
            }
            if (slugOut && slugOut.value) {
                byId("slug").value = _firstLine(slugOut.value);
            }
            syncSlugFromPrimary();

            // Ensure the editor content is formatted SEO-friendly (H1/H2/H3, paragraphs, lists).
            // Only run formatter when content is plain text / markdown-like (avoid double-formatting HTML).
            try {
                const cur = String(getContentValue() || "");
                const looksLikeHtml = /<\s*[a-z][^>]*>/i.test(cur);
                const looksLikeMd = /(^|\n)\s{0,3}(#|[-*]\s+|\d+[.)]\s+)/.test(cur);
                if (!looksLikeHtml && (looksLikeMd || cur.includes("\n"))) {
                    formatContentSeo();
                }
            } catch (_) {}

            const draftPayload = buildDraftPayload();
            const draftRes = await fetchDraftOutput(draftPayload);
            const newPid = draftRes && draftRes.project_id ? String(draftRes.project_id).trim() : "";
            if (newPid) activeProjectId = newPid;
            const autoImgEl = byId("autoInsertImagesAfterWrite");
            const imgSrc = typeof getAutoInsertImageSource === "function" ? getAutoInsertImageSource() : "google";
            if (newPid && autoImgEl && autoImgEl.checked && imgSrc !== "none") {
                msg.textContent = "Đang tìm và chèn ảnh minh họa vào bài…";
                try {
                    const imgData = await autoInsertImagesForProject(newPid, {
                        force: false,
                        image_source: imgSrc,
                    });
                    const n = Number(imgData.inline_images_count) || 0;
                    msg.textContent =
                        n > 0
                            ? `Đã tạo content và chèn ${n} ảnh vào bài.`
                            : "Đã tạo content; không lấy được ảnh phù hợp.";
                } catch (imgErr) {
                    msg.textContent = `Content xong; không lấy được ảnh phù hợp.`;
                }
            }
            await refreshProjects(true);
            rememberTargetWebsite(byId("targetWebsite").value);
            msg.textContent = `Đã tạo content thành công. Output đang ở chế độ ${getOutputFormat() === "json" ? "JSON" : "chữ thường"}.`;
            showCaToast("Đã tạo content thành công.", "success");
            byId("content").scrollIntoView({ behavior: "smooth", block: "center" });
            saveFormState();
        } catch (e) {
            if (_contentWriteSession.userAborted) {
                showCaToast("Đã dừng viết.", "info");
                msg.textContent = "Đã dừng viết.";
                saveFormState();
                return;
            }
            msg.textContent = String(e.message || e);
            showCaToast(String(e.message || e), "error");
        } finally {
            if (_contentWriteSession.active) _resetContentWriteUi();
        }
    });

    if (btnSeoJsonFill) {
        btnSeoJsonFill.addEventListener("click", async () => {
            const keyword = byId("primaryKeyword").value.trim();
            if (!keyword) {
                setHint("primary_keyword", "Vui lòng nhập keyword chính trước.");
                return;
            }
            const secondaryRaw = byId("secondaryKeywords").value || "";
            const secondary = secondaryRaw
                .split(",")
                .map((x) => x.trim())
                .filter(Boolean)
                .slice(0, 20);
            const outline = byId("outlineContent").value || "";
            const contextData = (byId("targetWebsite").value || "").trim();
            const intent = window.prompt("Search intent (ví dụ: thông tin / so sánh / mua dịch vụ...):", "") || "";
            const audience = window.prompt("Đối tượng đọc (ví dụ: người mới / chủ doanh nghiệp...):", "") || "";
            const brand = window.prompt("Brand (tên thương hiệu):", "") || "";

            const oldText = btnSeoJsonFill.textContent;
            btnSeoJsonFill.textContent = "Đang tạo SEO JSON...";
            btnSeoJsonFill.disabled = true;
            try {
                setHint("wp", "");
                const res = await fetch(`/content-ai/article-json?ts=${Date.now()}`, {
                    method: "POST",
                    headers: authJsonHeaders(),
                    body: JSON.stringify({
                        keyword: keyword,
                        secondary_keywords: secondary,
                        intent: intent,
                        audience: audience,
                        brand_name: brand,
                        outline: outline,
                        context_data: contextData,
                    }),
                });
                const data = await res.json().catch(() => ({}));
                if (!res.ok) throw new Error((data && data.detail) ? data.detail : "Không tạo được SEO JSON.");
                const final = (window.SeoautoAwaitQueued)
                    ? await window.SeoautoAwaitQueued(data, { headers: authJsonHeaders() })
                    : data;

                // Fill form fields
                if (final.title) byId("title").value = String(final.title || "");
                if (final.meta_description) byId("meta").value = String(final.meta_description || "");
                if (final.slug) byId("slug").value = String(final.slug || "");
                if (Array.isArray(final.tags)) byId("tags").value = (final.tags || []).join(", ");
                if (final.content_html) setContentValue(String(final.content_html || ""));

                // Put full JSON (incl. schema) into Output
                if (outputFormat) outputFormat.value = "json";
                try { persistOutputFormat(); } catch (_) {}
                out.value = JSON.stringify(final, null, 2);

                refreshPreview();
                saveFormState();
                appendPublishLog("OK: Đã đổ title/meta/slug/tags/content + schema vào Output (JSON).");
            } catch (e) {
                appendPublishLog(`Lỗi SEO JSON: ${String((e && e.message) || e)}`);
            } finally {
                btnSeoJsonFill.textContent = oldText;
                btnSeoJsonFill.disabled = false;
            }
        });
    }

    const btnSingleLoadWpCategories = byId("btnSingleLoadWpCategories");
    const singleWpCategoryIdEl = byId("singleWpCategoryId");
    if (btnSingleLoadWpCategories) {
        btnSingleLoadWpCategories.addEventListener("click", () => {
            btnSingleLoadWpCategories.disabled = true;
            void loadSingleWpCategories({ forceRefresh: true }).finally(() => {
                btnSingleLoadWpCategories.disabled = false;
            });
        });
    }
    if (singleWpCategoryIdEl) {
        singleWpCategoryIdEl.addEventListener("change", () => {
            syncSingleWpCategoryFromSelect();
            try {
                _rememberWpCategorySelection(
                    String(byId("targetWebsite")?.value || ""),
                    "",
                    String(singleWpCategoryIdEl.value || ""),
                );
            } catch (_) {}
            saveFormState();
        });
    }

    if (btn) btn.addEventListener("click", async () => {
        const payload = buildDraftPayload();
        const title = payload.title || "";
        const content = payload.content || "";
        const outline = payload.outline_content || "";
        const primaryKeyword = payload.primary_keyword || "";
        if (!primaryKeyword) {
            msg.textContent = "Can nhap tu khoa chinh truoc.";
            return;
        }
        if (!title || (!content && !outline)) {
            msg.textContent = "Can nhap title va content hoac outline.";
            return;
        }
        msg.textContent = "Đang tạo draft...";
        try {
            await fetchDraftOutput(payload);
            msg.textContent = `Đã tạo draft (${getOutputFormat() === "json" ? "JSON" : "chữ thường"}).`;
            activeProjectId = "";
            await refreshProjects(true);
            rememberTargetWebsite(byId("targetWebsite").value);
            saveFormState();
        } catch (e) {
            msg.textContent = String(e.message || e);
        }
    });

    if (outputFormat) {
        restoreOutputFormat();
        outputFormat.addEventListener("change", () => {
            persistOutputFormat();
            saveFormState();
        });
    }

    restoreOutputAccordion();
    if (btnToggleOutput) {
        const toggle = () => setOutputAccordionOpen(!outputAccordion.classList.contains("open"));
        btnToggleOutput.addEventListener("click", toggle);
        btnToggleOutput.addEventListener("keydown", (e) => {
            if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                toggle();
            }
        });
    }

    const _getPublishMode = () => {
        const mode = byId("caPublishStatus");
        return mode && String(mode.value || "draft") === "publish" ? "publish" : "draft";
    };
    if (btnPublishNow) {
        btnPublishNow.addEventListener("click", async () => {
            if (btnPublishNow.disabled) return;
            const cred = await resolveWpPublishCredentialsAsync();
            const wpUrl = cred.wpUrl;
            const wpUsername = cred.username;
            const wpAppPassword = cred.app_password;
            const wpSeoPlugin = cred.seo_plugin;
            const primaryKeyword = byId("primaryKeyword").value.trim();
            const title = byId("title").value.trim();
            const content = getContentValue().trim();
            const publishMode = _getPublishMode();
            if (!wpUrl || !primaryKeyword || !title || !content) {
                const miss = "Vui lòng nhập URL WordPress, từ khóa, tiêu đề và nội dung.";
                if (msg) msg.textContent = miss;
                appendPublishLog(miss);
                return;
            }
            if (!wpUsername || !wpAppPassword) {
                const missCred =
                    "Chưa lấy được username/app password từ site đã lưu. Mở Edit site, kiểm tra đã «Lưu & áp dụng» đủ thông tin trên server, rồi thử lại.";
                if (msg) msg.textContent = missCred;
                appendPublishLog(missCred);
                return;
            }
            if (publishMode === "publish") {
                const ok = window.confirm("Đăng bài ngay (Publish)? Nếu có hẹn giờ tương lai, hệ thống sẽ schedule.");
                if (!ok) return;
            }
            publishLog.value = "";
            appendPublishLog(
                publishMode === "publish"
                    ? "Bắt đầu đăng bài lên WordPress..."
                    : "Bắt đầu đăng bản nháp lên WordPress..."
            );
            if (msg) {
                msg.textContent =
                    publishMode === "publish"
                        ? "Đang đăng bài lên WordPress..."
                        : "Đang đăng bản nháp lên WordPress...";
            }
            const oldPublishText = btnPublishNow.textContent;
            btnPublishNow.disabled = true;
            btnPublishNow.classList.add("loading");
            btnPublishNow.textContent = publishMode === "publish" ? "Đang đăng bài..." : "Đang đăng bản nháp...";
            try {
                const draftPayload = await ensureDraftPayloadForPublish();
                appendPublishLog("Đã có draft payload.");
                const res = await fetch("/content-ai/publish-draft", {
                    method: "POST",
                    headers: authJsonHeaders(),
                    body: JSON.stringify({
                        wp_url: wpUrl,
                        username: wpUsername,
                        app_password: wpAppPassword,
                        seo_plugin: wpSeoPlugin,
                        primary_keyword: primaryKeyword,
                        publish_mode: publishMode,
                        draft_payload: draftPayload,
                    }),
                });
                let data = await res.json().catch(() => ({}));
                if (!res.ok) {
                    if (window.ContentAiUsage && window.ContentAiUsage.handleQuotaResponse(res, data)) {
                        throw new Error("Đã hết quota — vui lòng nâng cấp gói.");
                    }
                    const detail = data && data.detail ? data.detail : {};
                    if (detail && Array.isArray(detail.logs)) {
                        setPublishLogLines(detail.logs);
                    } else if (detail && typeof detail === "string") {
                        appendPublishLog(detail);
                    } else if (detail && typeof detail.message === "string") {
                        appendPublishLog(detail.message);
                    } else {
                        appendPublishLog(JSON.stringify(detail || data));
                    }
                    throw new Error((detail && detail.message) ? detail.message : "Publish thất bại.");
                }
                if (window.SeoautoAwaitQueued && data.job_id && data.poll_url) {
                    appendPublishLog("Đã xếp hàng crawl worker — đang chờ publish…");
                    data = await window.SeoautoAwaitQueued(data, { headers: authJsonHeaders() });
                }
                if (window.ContentAiUsage && window.ContentAiUsage.refresh) void window.ContentAiUsage.refresh();
                if (Array.isArray(data.logs)) setPublishLogLines(data.logs);
                appendPublishLog(
                    `Thành công: post_id=${data.post_id || ""}, status=${data.status || ""}, link=${data.link || "—"}`
                );
                if (msg) {
                    msg.textContent =
                        publishMode === "publish"
                            ? "Đăng bài thành công lên WordPress."
                            : "Đăng bản nháp thành công lên WordPress.";
                }
                rememberTargetWebsite(byId("targetWebsite").value);
                rememberWpUrl(wpUrl);
                rememberWpUser(wpUsername);
                saveFormState();
            } catch (e) {
                if (msg) msg.textContent = String(e.message || e);
                appendPublishLog(`Lỗi: ${String(e.message || e)}`);
            } finally {
                btnPublishNow.disabled = false;
                btnPublishNow.classList.remove("loading");
                btnPublishNow.textContent = oldPublishText;
            }
        });
    }

    if (btnWpUpdateContent) {
        btnWpUpdateContent.addEventListener("click", async () => {
            const cred = await resolveWpPublishCredentialsAsync();
            const wpUrl = cred.wpUrl;
            const wpUsername = cred.username;
            const wpAppPassword = cred.app_password;
            if (!wpUrl) {
                appendPublishLog("Thiếu WP URL.");
                return;
            }
            if (!wpUsername || !wpAppPassword) {
                appendPublishLog(
                    "Chưa lấy được username/app password từ site đã lưu — mở Edit / Thêm site đăng bài và «Lưu & áp dụng»."
                );
                return;
            }
            const postIdRaw = window.prompt("Nhập Post ID cần cập nhật (ví dụ: 123):", "");
            const postId = Number(String(postIdRaw || "").trim());
            if (!Number.isFinite(postId) || postId <= 0) {
                appendPublishLog("Post ID không hợp lệ.");
                return;
            }
            const ok = window.confirm(`Cập nhật content hiện tại lên WordPress?\\nPost ID: ${postId}`);
            if (!ok) return;
            try {
                btnWpUpdateContent.disabled = true;
                appendPublishLog(`Đang cập nhật Post ID ${postId}...`);
                const res = await fetch("/wp/update-post", {
                    method: "POST",
                    headers: authJsonHeaders(),
                    body: JSON.stringify({
                        wp_url: wpUrl,
                        username: wpUsername,
                        app_password: wpAppPassword,
                        post_type: "posts",
                        post_id: postId,
                        content_html: getContentValue(),
                        dry_run: false,
                    }),
                });
                const d = await res.json().catch(() => ({}));
                if (!res.ok) throw new Error((d && (d.detail || d.message)) ? String(d.detail || d.message) : "Update failed");
                appendPublishLog(`OK: Đã cập nhật. Link: ${d.link || "—"}`);
            } catch (e) {
                appendPublishLog(`Lỗi cập nhật: ${String((e && e.message) || e)}`);
            } finally {
                btnWpUpdateContent.disabled = false;
            }
        });
    }

    // Remember WP URL as user types/leaves field (builds history even before publish).
    const wpUrlEl = byId("wpUrl");
    if (wpUrlEl) {
        const onWpUrlSiteChange = () => {
            rememberWpUrl(wpUrlEl.value);
            fillWpCredentialsFromSavedProfile();
            schedulePublishWpCategoriesLoad();
        };
        wpUrlEl.addEventListener("blur", onWpUrlSiteChange);
        wpUrlEl.addEventListener("change", onWpUrlSiteChange);
        wpUrlEl.addEventListener("input", schedulePublishWpCategoriesLoad);
    }

    if (btnModeVisual) {
        btnModeVisual.addEventListener("click", () => {
            editorMode = "visual";
            try { if (window.tinymce && tinymce.get("content")) tinymce.get("content").save(); } catch (_) {}
            refreshEditorModeUi();
            refreshPreview();
        });
    }
    if (btnModeCode) {
        btnModeCode.addEventListener("click", () => {
            if (FORCE_VISUAL_MODE) return;
            editorMode = "code";
            const ta = byId("content");
            if (ta) ta.value = getContentValue();
            refreshEditorModeUi();
        });
    }
    if (btnToolBold) btnToolBold.addEventListener("click", () => execEditorCommand("bold"));
    if (btnToolItalic) btnToolItalic.addEventListener("click", () => execEditorCommand("italic"));
    if (btnToolUnderline) btnToolUnderline.addEventListener("click", () => execEditorCommand("underline"));
    if (btnToolQuote) btnToolQuote.addEventListener("click", () => execEditorCommand("blockquote"));
    if (btnToolH2) btnToolH2.addEventListener("click", () => execEditorCommand("h2"));
    if (btnToolH3) btnToolH3.addEventListener("click", () => execEditorCommand("h3"));
    if (btnToolUl) btnToolUl.addEventListener("click", () => execEditorCommand("ul"));
    if (btnToolOl) btnToolOl.addEventListener("click", () => execEditorCommand("ol"));
    if (btnToolAlignLeft) btnToolAlignLeft.addEventListener("click", () => execEditorCommand("align-left"));
    if (btnToolAlignCenter) btnToolAlignCenter.addEventListener("click", () => execEditorCommand("align-center"));
    if (btnToolAlignRight) btnToolAlignRight.addEventListener("click", () => execEditorCommand("align-right"));
    if (btnToolUndo) btnToolUndo.addEventListener("click", () => execEditorCommand("undo"));
    if (btnToolRedo) btnToolRedo.addEventListener("click", () => execEditorCommand("redo"));
    if (btnToolLink) btnToolLink.addEventListener("click", () => execEditorCommand("link"));
    if (btnToolHr) btnToolHr.addEventListener("click", () => execEditorCommand("hr"));
    if (btnToolTable) btnToolTable.addEventListener("click", () => execEditorCommand("table"));
    if (btnToolClear) btnToolClear.addEventListener("click", () => execEditorCommand("clear"));
    if (editorBlockFormat) {
        editorBlockFormat.addEventListener("change", () => {
            const v = String(editorBlockFormat.value || "");
            if (v === "blockquote") execEditorCommand("blockquote");
            else if (v === "h1") execEditorCommand("h1");
            else if (v === "h2") execEditorCommand("h2");
            else if (v === "h3") execEditorCommand("h3");
            else if (v === "h4") execEditorCommand("h4");
            else if (v === "h5") execEditorCommand("h5");
            else if (v === "h6") execEditorCommand("h6");
            else execEditorCommand("paragraph");
        });
    }
    let _lastScreamingFrogTsv = "";
    const LEGACY_CUSTOM_LINK_LIB_KEY = "digiseo_content_ai_custom_link_library";
    const getCustomLinkRowsEl = () => document.getElementById("customLinkRows");
    const customLinkLibraryList = byId("customLinkLibraryList");
    const internalLinkApplyResults = byId("internalLinkApplyResults");
    const btnAddCustomLink = byId("btnAddCustomLink");
    const btnSaveCustomToLibrary = byId("btnSaveCustomToLibrary");
    const btnApplyCustomInternalLinks = byId("btnApplyCustomInternalLinks");
    const customLinkUseLlm = byId("customLinkUseLlm");
    const hintCustomLinkApply = byId("hint-custom-link-apply");
    if (customLinkUseLlm && !customLinkUseLlm.dataset.llmSwitchBound) {
        customLinkUseLlm.dataset.llmSwitchBound = "1";
        syncLlmSwitchHighlight(customLinkUseLlm);
        customLinkUseLlm.addEventListener("change", () => syncLlmSwitchHighlight(customLinkUseLlm));
    }
    let _customLinkRowSeq = 0;

    const customLinkUrlHost = (url) => {
        try {
            let h = new URL(String(url || "").includes("://") ? url : `https://${url}`).hostname.toLowerCase();
            if (h.startsWith("www.")) h = h.slice(4);
            return h;
        } catch (_) {
            return "";
        }
    };
    const customLinkBelongsToSite = (linkUrl, siteBase) => {
        const lh = customLinkUrlHost(linkUrl);
        const sh = customLinkUrlHost(siteBase);
        if (!lh || !sh) return false;
        return lh === sh || lh.endsWith(`.${sh}`) || sh.endsWith(`.${lh}`);
    };
    const getCustomLinkLibraryScope = () => {
        const pid = String(activeProjectId || "").trim();
        if (pid) {
            const p = (allProjects || []).find((x) => String(x.id) === pid);
            const tw = normalizeTargetBase(String((p && p.target_website) || byId("targetWebsite")?.value || ""));
            let label = String((p && (p.title || p.primary_keyword)) || "").trim();
            if (!label && tw) label = connectedSiteHostLabel(tw);
            if (!label) label = "Dự án hiện tại";
            return { ok: true, type: "project", storageId: `p_${pid}`, label, siteBase: tw };
        }
        const tw = normalizeTargetBase(String(byId("targetWebsite")?.value || "").trim());
        if (tw) {
            const sk = connectedSiteKey(tw) || tw;
            return {
                ok: true,
                type: "site",
                storageId: `s_${sk.replace(/[^a-zA-Z0-9._-]+/g, "_").slice(0, 120)}`,
                label: connectedSiteHostLabel(tw),
                siteBase: tw,
            };
        }
        return { ok: false, type: "none", storageId: "", label: "", siteBase: "" };
    };
    const customLinkLibraryStorageKey = () => {
        const scope = getCustomLinkLibraryScope();
        if (!scope.ok || !scope.storageId) return "";
        return userStorageKey(`content_ai_custom_link_library_v2_${scope.storageId}`);
    };
    const loadLegacyGlobalCustomLinkLibrary = () => {
        try {
            const raw = localStorage.getItem(LEGACY_CUSTOM_LINK_LIB_KEY);
            const arr = raw ? JSON.parse(raw) : [];
            return Array.isArray(arr) ? arr : [];
        } catch (_) {
            return [];
        }
    };
    const tryMigrateLegacyCustomLinkLibrary = (scope) => {
        if (!scope.ok || !scope.siteBase) return;
        const key = customLinkLibraryStorageKey();
        if (!key) return;
        try {
            if (localStorage.getItem(key)) return;
        } catch (_) {
            return;
        }
        const legacy = loadLegacyGlobalCustomLinkLibrary();
        if (!legacy.length) return;
        const migrated = legacy.filter((it) => customLinkBelongsToSite(it && it.target_url, scope.siteBase));
        if (!migrated.length) return;
        try {
            localStorage.setItem(key, JSON.stringify(migrated.slice(0, 80)));
        } catch (_) { /* ignore */ }
    };
    const loadCustomLinkLibrary = () => {
        const scope = getCustomLinkLibraryScope();
        if (!scope.ok) return [];
        tryMigrateLegacyCustomLinkLibrary(scope);
        const key = customLinkLibraryStorageKey();
        if (!key) return [];
        try {
            const raw = localStorage.getItem(key);
            const arr = raw ? JSON.parse(raw) : [];
            if (!Array.isArray(arr)) return [];
            if (!scope.siteBase) return arr;
            return arr.filter((it) => customLinkBelongsToSite(it && it.target_url, scope.siteBase));
        } catch (_) {
            return [];
        }
    };
    const saveCustomLinkLibrary = (items) => {
        const scope = getCustomLinkLibraryScope();
        if (!scope.ok) return false;
        const key = customLinkLibraryStorageKey();
        if (!key) return false;
        let clean = (items || []).map((x) => ({ ...x }));
        if (scope.siteBase) {
            clean = clean.filter((it) => customLinkBelongsToSite(it.target_url, scope.siteBase));
        }
        try {
            localStorage.setItem(key, JSON.stringify(clean.slice(0, 80)));
            return true;
        } catch (_) {
            return false;
        }
    };
    const renderCustomLinkLibrary = () => {
        if (!customLinkLibraryList) return;
        const scope = getCustomLinkLibraryScope();
        const hintLib = byId("hint-custom-link-library");
        if (hintLib) {
            hintLib.textContent = scope.ok
                ? `Thư viện riêng cho ${scope.type === "project" ? "dự án" : "site"} «${scope.label}» — không hiện link của dự án/site khác.`
                : "Mở một dự án hoặc nhập Target website để lưu / xem thư viện custom link.";
        }
        if (btnSaveCustomToLibrary) {
            btnSaveCustomToLibrary.disabled = !scope.ok;
            btnSaveCustomToLibrary.title = scope.ok
                ? `Lưu vào thư viện của ${scope.label}`
                : "Cần dự án hoặc Target website";
        }
        const lib = loadCustomLinkLibrary();
        customLinkLibraryList.innerHTML = "";
        if (!scope.ok) {
            customLinkLibraryList.innerHTML =
                "<div class=\"hint\">Chưa gắn dự án hoặc Target website. Mở dự án (ví dụ backlinkbrand) rồi mới lưu link money page cho đúng bài.</div>";
            return;
        }
        if (!lib.length) {
            customLinkLibraryList.innerHTML =
                "<div class=\"hint\">Thêm custom link rồi bấm «Lưu dòng đã chọn vào thư viện».</div>";
            return;
        }
        lib.forEach((it, idx) => {
            const row = document.createElement("div");
            row.className = "custom-link-lib-item";
            const meta = document.createElement("div");
            meta.style.minWidth = "0";
            const t = document.createElement("div");
            t.textContent = String(it.anchor_text || "").trim() || "(anchor)";
            t.style.fontWeight = "700";
            const u = document.createElement("div");
            u.className = "hint";
            u.textContent = String(it.target_url || "").trim();
            u.style.wordBreak = "break-all";
            meta.appendChild(t);
            meta.appendChild(u);
            const actions = document.createElement("div");
            actions.style.display = "flex";
            actions.style.gap = "4px";
            const btnUse = document.createElement("button");
            btnUse.type = "button";
            btnUse.className = "mini-btn";
            btnUse.textContent = "Dùng";
            btnUse.addEventListener("click", () => addCustomLinkRow(it));
            const btnDel = document.createElement("button");
            btnDel.type = "button";
            btnDel.className = "mini-btn danger";
            btnDel.textContent = "Xóa";
            btnDel.addEventListener("click", () => {
                const next = loadCustomLinkLibrary().filter((_, i) => i !== idx);
                saveCustomLinkLibrary(next);
                renderCustomLinkLibrary();
            });
            actions.appendChild(btnUse);
            actions.appendChild(btnDel);
            row.appendChild(meta);
            row.appendChild(actions);
            customLinkLibraryList.appendChild(row);
        });
    };
    const normalizeCustomUrl = (raw) => {
        let s = String(raw || "").trim();
        if (!s) return "";
        if (!/^https?:\/\//i.test(s)) s = `https://${s.replace(/^\/+/, "")}`;
        return s;
    };
    const addCustomLinkRow = (seed) => {
        const customLinkRows = getCustomLinkRowsEl();
        if (!customLinkRows) return;
        const id = ++_customLinkRowSeq;
        const s = seed && typeof seed === "object" ? seed : {};
        const row = document.createElement("div");
        row.className = "custom-link-row";
        row.setAttribute("data-custom-id", String(id));
        row.innerHTML = `
            <input type="checkbox" class="custom-link-cb" data-custom-id="${id}" checked title="Chọn" />
            <input type="text" class="cl-url" inputmode="url" autocomplete="url" placeholder="https://..." value="${String(s.target_url || "").replace(/"/g, "&quot;")}" />
            <input type="text" class="cl-anchor" placeholder="Anchor text" value="${String(s.anchor_text || "").replace(/"/g, "&quot;")}" />
            <select class="cl-type">
                <option value="money_page">money_page</option>
                <option value="blog">blog</option>
                <option value="category">category</option>
                <option value="service">service</option>
                <option value="course">course</option>
                <option value="manual">manual</option>
            </select>
            <select class="cl-priority">
                <option value="high">high</option>
                <option value="medium">medium</option>
                <option value="low">low</option>
            </select>
            <input type="number" class="cl-max" min="1" max="3" value="${Number(s.max_insert) > 0 ? Number(s.max_insert) : 1}" title="max_insert" />
            <button type="button" class="mini-btn danger cl-del" title="Xóa dòng">×</button>
        `;
        const typeSel = row.querySelector(".cl-type");
        const priSel = row.querySelector(".cl-priority");
        if (typeSel && s.link_type) typeSel.value = String(s.link_type);
        if (priSel && s.priority) priSel.value = String(s.priority);
        row.querySelector(".cl-del")?.addEventListener("click", () => {
            row.remove();
            syncIlSelectedPanel();
        });
        row.addEventListener("input", () => syncIlSelectedPanel());
        row.addEventListener("change", () => syncIlSelectedPanel());
        customLinkRows.appendChild(row);
        syncIlSelectedPanel();
    };
    const collectCheckedCustomLinks = () => {
        const root = byId("internalLinkPanel") || getCustomLinkRowsEl();
        if (!root) return [];
        const out = [];
        root.querySelectorAll(".custom-link-row").forEach((row) => {
            const cbs = row.querySelectorAll("input.custom-link-cb[type='checkbox'], input.custom-link-cb");
            const hasCheckbox = cbs.length > 0;
            const isChecked = !hasCheckbox || Array.from(cbs).some((c) => c.checked);
            if (!isChecked) return;
            const url = normalizeCustomUrl(row.querySelector(".cl-url")?.value);
            const anchor = String(row.querySelector(".cl-anchor")?.value || "").trim();
            if (!url && !anchor) return;
            out.push({
                target_url: url,
                anchor_text: anchor,
                link_type: String(row.querySelector(".cl-type")?.value || "manual"),
                priority: String(row.querySelector(".cl-priority")?.value || "medium"),
                max_insert: Math.max(1, Math.min(3, Number(row.querySelector(".cl-max")?.value) || 1)),
            });
        });
        return out;
    };
    const getValidCustomLinksForApply = () =>
        collectCheckedCustomLinks().filter((x) => x.target_url && x.anchor_text);
    const escapeHtml = (s) => String(s || "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;");
    let _ilContentBeforeApply = "";
    const showIlInsertSummary = (text, { warn = false } = {}) => {
        const box = byId("ilInsertSummary");
        if (!box) return;
        const msg = String(text || "").trim();
        if (!msg) {
            box.hidden = true;
            box.textContent = "";
            box.classList.remove("warn");
            return;
        }
        box.hidden = false;
        box.textContent = msg;
        box.classList.toggle("warn", !!warn);
        const statsEl = byId("ilInsertedStatsText");
        if (statsEl) statsEl.textContent = msg;
    };
    const switchIlToInsertedTab = () => {
        const root = byId("internalLinkPanel");
        if (root && window.__caSwitchModalTab) window.__caSwitchModalTab(root, 2);
    };
    const syncIlSelectedPanel = () => {
        const host = byId("ilSelectedLinks");
        if (!host) return;
        const wp = collectWpInternalChecked();
        const custom = getValidCustomLinksForApply();
        const chips = [];
        wp.forEach((p) => {
            chips.push({ label: p.anchor_text || p.title, sub: p.link });
        });
        custom.forEach((p) => {
            chips.push({ label: p.anchor_text, sub: p.target_url });
        });
        if (!chips.length) {
            host.innerHTML = '<p class="ca-il-empty">Chưa chọn link — tick gợi ý hoặc thêm custom link.</p>';
            return;
        }
        host.innerHTML = "";
        chips.forEach((c) => {
            const row = document.createElement("div");
            row.className = "ca-il-selected-chip";
            row.innerHTML = `<strong>${escapeHtml(c.label)}</strong><span class="hint">${escapeHtml(c.sub)}</span>`;
            host.appendChild(row);
        });
    };
    const _inferIlH2Hint = () => {
        const html = String(getContentValue() || "");
        const m = html.match(/<h2\b[^>]*>(.*?)<\/h2>/i);
        if (!m) return "Tự động theo mục H2 gần anchor";
        return String(m[1] || "").replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim().slice(0, 80) || "Tự động theo H2";
    };
    const _getInternalRowEl = (idx) =>
        document.querySelector(`.ca-il-card[data-idx="${idx}"], tr[data-idx="${idx}"]`);
    const renderInternalApplyResults = (rows) => {
        if (!internalLinkApplyResults) return;
        const arr = Array.isArray(rows) ? rows : [];
        if (!arr.length) {
            internalLinkApplyResults.style.display = "none";
            internalLinkApplyResults.innerHTML = "";
            return;
        }
        internalLinkApplyResults.style.display = "block";
        internalLinkApplyResults.innerHTML = "";
        arr.forEach((r) => {
            const st = String(r.status || "");
            const row = document.createElement("div");
            row.className = "ca-il-result-row";
            const ok = st === "inserted";
            row.innerHTML = `
                <span class="il-row-circle ${ok ? "il-done" : ""}">${ok ? "✓" : "·"}</span>
                <div>
                    <strong>${escapeHtml(String(r.anchor_text || ""))}</strong>
                    <div class="hint" style="word-break:break-all;">${escapeHtml(String(r.target_url || ""))}</div>
                    ${r.reason ? `<div class="hint">${escapeHtml(String(r.reason))}</div>` : ""}
                </div>
            `;
            internalLinkApplyResults.appendChild(row);
        });
        const inserted = arr.filter((r) => String(r.status) === "inserted").length;
        showIlInsertSummary(
            inserted
                ? `Đã chèn ${inserted} link vào bài. Kiểm tra editor bên trái.`
                : "Không chèn được link nào — xem chi tiết bên dưới.",
            { warn: !inserted }
        );
    };
    if (btnAddCustomLink) btnAddCustomLink.addEventListener("click", () => addCustomLinkRow({ link_type: "money_page", priority: "high" }));
    if (btnSaveCustomToLibrary) {
        btnSaveCustomToLibrary.addEventListener("click", () => {
            const scope = getCustomLinkLibraryScope();
            if (!scope.ok) {
                setHint(
                    "content",
                    "Mở dự án hoặc nhập Target website trước khi lưu thư viện custom link."
                );
                return;
            }
            const picked = getValidCustomLinksForApply();
            if (!picked.length) {
                setHint("content", "Chọn ít nhất một custom link hợp lệ (URL + anchor) để lưu thư viện.");
                return;
            }
            const mismatched = scope.siteBase
                ? picked.filter((p) => !customLinkBelongsToSite(p.target_url, scope.siteBase))
                : [];
            if (mismatched.length) {
                setHint(
                    "content",
                    `Có ${mismatched.length} link không thuộc site «${scope.label}» — chỉ lưu link cùng domain Target website.`
                );
                return;
            }
            const lib = loadCustomLinkLibrary();
            picked.forEach((p) => {
                const dup = lib.some(
                    (x) => String(x.target_url).trim() === p.target_url && String(x.anchor_text).trim() === p.anchor_text
                );
                if (!dup) lib.unshift({ ...p, saved_at: Date.now(), scope_label: scope.label });
            });
            if (!saveCustomLinkLibrary(lib)) {
                setHint("content", "Không ghi được thư viện (localStorage).");
                return;
            }
            renderCustomLinkLibrary();
            setHint("content", `Đã lưu ${picked.length} link vào thư viện «${scope.label}».`);
        });
    }
    renderCustomLinkLibrary();
    const targetWebsiteForCustomLib = byId("targetWebsite");
    if (targetWebsiteForCustomLib) {
        let _customLibRefreshTimer = null;
        const scheduleCustomLibRefresh = () => {
            if (_customLibRefreshTimer) clearTimeout(_customLibRefreshTimer);
            _customLibRefreshTimer = setTimeout(() => {
                try {
                    renderCustomLinkLibrary();
                } catch (_) {}
            }, 300);
        };
        targetWebsiteForCustomLib.addEventListener("input", scheduleCustomLibRefresh);
        targetWebsiteForCustomLib.addEventListener("change", scheduleCustomLibRefresh);
    }
    const _currentUrlGuess = () => {
        const site = String(byId("targetWebsite").value || "").trim().replace(/\/+$/, "");
        const slug = String(byId("slug").value || "").trim().replace(/^\/+/, "");
        if (!site) return "";
        return slug ? `${site}/${slug}` : site;
    };
    const _mountIlAdvancedLlm = () => {
        const slot = byId("ilAdvancedLlmSlot");
        if (!slot || slot.dataset.mounted) return;
        slot.dataset.mounted = "1";
        const llmLbl = document.createElement("label");
        llmLbl.className = "il-llm-switch";
        if (getInternalLinkUseLlm()) llmLbl.classList.add("is-on");
        const llmInp = document.createElement("input");
        llmInp.type = "checkbox";
        llmInp.id = "internalLinkUseLlm";
        llmInp.className = "il-llm-switch-input";
        llmInp.checked = getInternalLinkUseLlm();
        const llmTrack = document.createElement("span");
        llmTrack.className = "il-llm-switch-track";
        llmTrack.setAttribute("aria-hidden", "true");
        const llmTxt = document.createElement("span");
        llmTxt.className = "il-llm-switch-text";
        llmTxt.textContent = "Dùng LLM khi rule không chèn được anchor";
        llmLbl.appendChild(llmInp);
        llmLbl.appendChild(llmTrack);
        llmLbl.appendChild(llmTxt);
        llmInp.addEventListener("change", () => {
            setInternalLinkUseLlm(llmInp.checked);
            llmLbl.classList.toggle("is-on", llmInp.checked);
        });
        slot.appendChild(llmLbl);
    };
    const renderInternalCandidates = (items) => {
        if (!internalLinkCandidates) return;
        internalLinkCandidates.innerHTML = "";
        _mountIlAdvancedLlm();
        const arr = Array.isArray(items) ? items : [];
        const hintIl = byId("hint-internal-links");
        if (hintIl) {
            hintIl.textContent = arr.length
                ? `${arr.length} gợi ý — chọn card và bấm «Chèn link vào bài».`
                : "Bấm «Tìm bài liên quan» khi đã có Target website.";
        }
        if (!arr.length) {
            internalLinkCandidates.innerHTML = '<p class="ca-il-empty">Không tìm thấy bài liên quan. Thử thêm từ khóa phụ hoặc nội dung liên quan trong bài.</p>';
            syncIlSelectedPanel();
            return;
        }
        const ptLabels = {
            money_page: "Money page",
            service: "Dịch vụ",
            pillar: "Pillar",
            course: "Khóa học",
            blog: "Blog",
            category: "Danh mục",
        };
        arr.forEach((it, idx) => {
            const displayTitle = String(it.title || "").trim()
                || String(it.slug || "").replace(/-/g, " ").trim()
                || String(it.link || "").trim()
                || `Bài liên quan #${idx + 1}`;
            const card = document.createElement("article");
            card.className = "ca-il-card";
            card.setAttribute("data-idx", String(idx));
            card.setAttribute("role", "listitem");
            const anchorDefault =
                String(it.suggested_anchor || it.anchor_text || it.target_primary_keyword || it.kw_hint_primary || "").trim() ||
                String(it.title || "").trim().split("|")[0].trim();
            const rel = Number(it.relevance_score);
            const relCls = rel >= 80 ? "high" : rel >= 60 ? "med" : "low";
            const pt = String(it.page_type || "").trim();
            const url = String(it.link || "");
            const shortUrl = url.length > 48 ? url.slice(0, 46) + "…" : url;
            card.innerHTML = `
                <div class="ca-il-card-head">
                    <input type="checkbox" class="internal-link-cb ca-il-card-check" data-idx="${idx}" checked aria-label="Chọn link" />
                    <div class="ca-il-card-title">${escapeHtml(displayTitle)}</div>
                    ${Number.isFinite(rel) ? `<span class="ca-il-relevance ${relCls}">${rel}%</span>` : ""}
                    <span class="il-row-circle il-row-status content-ai-aux-hidden" data-idx="${idx}" aria-hidden="true"></span>
                </div>
                <div class="ca-il-card-url" title="${escapeHtml(url)}">${escapeHtml(shortUrl)}</div>
                <div class="ca-il-card-field">
                    <input type="text" class="internal-link-anchor-input" data-idx="${idx}" placeholder="Anchor đề xuất" value="${escapeHtml(anchorDefault.slice(0, 120))}" />
                </div>
                <div class="ca-il-card-actions">
                    <button type="button" class="mini-btn ca-il-btn-edit" data-idx="${idx}">Sửa anchor</button>
                </div>
            `;
            const cb = card.querySelector(".internal-link-cb");
            if (cb) {
                cb.addEventListener("change", () => {
                    card.classList.toggle("is-selected", cb.checked);
                    syncIlSelectedPanel();
                    scheduleSaveFormState();
                });
            }
            card.querySelector(".ca-il-btn-edit")?.addEventListener("click", (ev) => {
                ev.preventDefault();
                const inp = card.querySelector(".internal-link-anchor-input");
                if (inp) inp.focus({ preventScroll: true });
            });
            if (cb && cb.checked) card.classList.add("is-selected");
            internalLinkCandidates.appendChild(card);
        });
        syncIlSelectedPanel();
    };
    if (btnFindInternalLinks) {
        btnFindInternalLinks.addEventListener("click", async (ev) => {
            ev.preventDefault();
            ev.stopPropagation();
            const siteRaw = String(byId("targetWebsite").value || "").trim();
            const site = normalizeTargetBase(siteRaw) || siteRaw;
            if (!site) {
                const msg = "Thiếu Target website — nhập https://domain.com ở form phía trên hoặc chọn site đã kết nối.";
                setHint("content", msg);
                setHint("internal-links", msg);
                return;
            }
            const oldText = btnFindInternalLinks.textContent;
            btnFindInternalLinks.textContent = "Đang tìm...";
            btnFindInternalLinks.disabled = true;
            setHint("internal-links", "Đang tìm bài trên WordPress + SERP…");
            try {
                const res = await apiFetch(`/content-ai/wp-internal-links/candidates?ts=${Date.now()}`, {
                    method: "POST",
                    headers: authJsonHeaders(),
                    body: JSON.stringify({
                        target_website: site,
                        primary_keyword: byId("primaryKeyword").value.trim(),
                        secondary_keywords: byId("secondaryKeywords").value.trim(),
                        content_html: getContentValue(),
                        current_slug: byId("slug").value.trim(),
                        current_url: _currentUrlGuess(),
                        limit: 15,
                    }),
                });
                let data = await res.json().catch(() => ({}));
                if (!res.ok) {
                    throw new Error(parseApiDetail(data) || "Không tìm được bài liên quan.");
                }
                if (window.SeoautoAwaitQueued && data.job_id && data.poll_url) {
                    data = await window.SeoautoAwaitQueued(data, { headers: authJsonHeaders() });
                }
                _internalCandidates = Array.isArray(data.items) ? data.items : [];
                renderInternalCandidates(_internalCandidates);
                saveFormState();
                const panel = byId("internalLinkPanel");
                if (panel) {
                    try { panel.scrollIntoView({ behavior: "smooth", block: "start" }); } catch (_) {}
                }
                if (_internalCandidates.length) {
                    const msg = `Tìm thấy ${_internalCandidates.length} bài — anchor = từ khóa chính bài đích (sửa từng ô nếu cần).`;
                    setHint("content", msg);
                    setHint("internal-links", msg);
                } else {
                    const apiHint = String(data.hint || "").trim();
                    const msg = apiHint || (
                        `Không có bài phù hợp (đã quét ${Number(data.wp_posts_fetched) || 0} URL). `
                        + "Thử nhập từ khóa chính, thêm H2 trong content, hoặc kiểm tra WP REST API công khai."
                    );
                    setHint("content", msg);
                    setHint("internal-links", msg);
                }
            } catch (e) {
                const errMsg = String((e && e.message) || e);
                setHint("content", errMsg);
                setHint("internal-links", errMsg);
            } finally {
                btnFindInternalLinks.textContent = oldText;
                btnFindInternalLinks.disabled = false;
            }
        });
    }
    const restoreInternalCandidatesFromPending = () => {
        try {
            const pending = _pendingInternalCandidatesRestore;
            if (!pending || !Array.isArray(pending.items) || !pending.items.length) return;
            _pendingInternalCandidatesRestore = null;
            _internalCandidates = pending.items;
            renderInternalCandidates(_internalCandidates);
            const anchors = pending.anchors && typeof pending.anchors === "object" ? pending.anchors : {};
            Object.keys(anchors).forEach((idx) => {
                const inp = document.querySelector(`input.internal-link-anchor-input[data-idx="${idx}"]`);
                if (inp) inp.value = String(anchors[idx] ?? "");
            });
            setHint(
                "internal-links",
                `Đã khôi phục ${_internalCandidates.length} bài liên quan (lưu trên trình duyệt). Tick → «Đi link» để chèn.`
            );
        } catch (e) {
            _pendingInternalCandidatesRestore = null;
            console.error("[content-ai] restore internal candidates failed", e);
        }
    };
    window.setTimeout(() => restoreInternalCandidatesFromPending(), 0);
    if (internalLinkCandidates && !internalLinkCandidates.dataset.persistBound) {
        internalLinkCandidates.dataset.persistBound = "1";
        internalLinkCandidates.addEventListener("input", (e) => {
            if (e.target && e.target.classList && e.target.classList.contains("internal-link-anchor-input")) {
                scheduleSaveFormState();
            }
        });
        internalLinkCandidates.addEventListener("change", (e) => {
            if (e.target && e.target.classList && e.target.classList.contains("internal-link-cb")) {
                scheduleSaveFormState();
                syncIlSelectedPanel();
            }
        });
    }
    const btnIlUndo = byId("btnIlUndo");
    if (btnIlUndo && !btnIlUndo.dataset.bound) {
        btnIlUndo.dataset.bound = "1";
        btnIlUndo.addEventListener("click", (e) => {
            e.preventDefault();
            if (!_ilContentBeforeApply) return;
            setContentValue(_ilContentBeforeApply);
            _ilContentBeforeApply = "";
            refreshPreview();
            saveFormState();
            btnIlUndo.hidden = true;
            showIlInsertSummary("Đã hoàn tác — khôi phục nội dung trước khi chèn link.");
        });
    }
    const collectWpInternalChecked = () =>
        Array.from(document.querySelectorAll(".internal-link-cb:checked"))
            .map((el) => Number(el.getAttribute("data-idx")))
            .filter((n) => Number.isFinite(n) && _internalCandidates[n])
            .map((n) => {
                const inp = document.querySelector(`input.internal-link-anchor-input[data-idx="${n}"]`);
                const anchor = inp ? String(inp.value || "").trim() : "";
                return {
                    title: _internalCandidates[n].title,
                    link: _internalCandidates[n].link,
                    anchor_text: anchor,
                };
            });

    const getInternalRowPost = (idx) => {
        const n = Number(idx);
        if (!Number.isFinite(n) || !_internalCandidates[n]) return null;
        const inp = document.querySelector(`input.internal-link-anchor-input[data-idx="${n}"]`);
        const anchor = inp ? String(inp.value || "").trim() : "";
        const it = _internalCandidates[n];
        const title = String(it.title || "").trim();
        const link = String(it.link || "").trim();
        if (!link) return null;
        return {
            title: title || anchor,
            link,
            anchor_text: anchor || title,
        };
    };

    const getInternalRowCircle = (idx) => {
        const row = _getInternalRowEl(idx);
        if (!row) return null;
        return row.querySelector(".il-row-circle");
    };

    const setInternalRowCircleState = (idx, state) => {
        const row = _getInternalRowEl(idx);
        const circle = getInternalRowCircle(idx);
        if (!row || !circle) return;
        circle.classList.remove("il-loading", "il-done", "il-error");
        circle.innerHTML = "";
        if (state === "loading") {
            circle.classList.add("il-loading");
            const sp = document.createElement("span");
            sp.className = "il-row-spinner";
            sp.setAttribute("aria-label", "Đang chèn link");
            circle.appendChild(sp);
            return;
        }
        if (state === "done") {
            row.classList.add("il-row-applied");
            circle.classList.add("il-done");
            circle.textContent = "✓";
            circle.title = "Đã chèn internal link";
            const cb = row.querySelector(".internal-link-cb");
            if (cb) cb.disabled = true;
            return;
        }
        if (state === "error") {
            circle.classList.add("il-error");
            circle.title = "Không chèn được — thử lại";
            return;
        }
        circle.title = "Chờ chèn link";
    };

    const getSelectedInternalRowIndices = () =>
        Array.from(document.querySelectorAll(".internal-link-cb:checked"))
            .map((el) => Number(el.getAttribute("data-idx")))
            .filter((n) => Number.isFinite(n) && _internalCandidates[n]);

    let _thamKhaoModalResolver = null;
    const closeThamKhaoAppendModal = () => {
        const modal = byId("thamKhaoAppendModal");
        if (modal) {
            modal.classList.remove("open");
            modal.setAttribute("aria-hidden", "true");
        }
        if (_thamKhaoModalResolver) {
            _thamKhaoModalResolver(null);
            _thamKhaoModalResolver = null;
        }
    };
    const showThamKhaoAppendModal = (offers) => {
        const list = Array.isArray(offers) ? offers : [];
        if (!list.length) return Promise.resolve(null);
        const modal = byId("thamKhaoAppendModal");
        const box = byId("thamKhaoAppendList");
        if (!modal || !box) return Promise.resolve(null);
        box.innerHTML = "";
        list.forEach((o, i) => {
            const row = document.createElement("label");
            row.className = "tham-khao-item";
            const cb = document.createElement("input");
            cb.type = "checkbox";
            cb.checked = true;
            cb.setAttribute("data-url", String(o.target_url || ""));
            cb.setAttribute("data-idx", String(o.row_idx != null ? o.row_idx : i));
            const prev = document.createElement("div");
            prev.className = "tham-khao-preview";
            const anchor = String(o.anchor_text || "").trim();
            const url = String(o.target_url || "").trim();
            prev.innerHTML = `Tham khảo thêm: <a href="${url.replace(/"/g, "&quot;")}" target="_blank" rel="noopener">${anchor.replace(/</g, "&lt;")}</a>.`;
            row.appendChild(cb);
            row.appendChild(prev);
            box.appendChild(row);
        });
        modal.classList.add("open");
        modal.setAttribute("aria-hidden", "false");
        return new Promise((resolve) => {
            _thamKhaoModalResolver = resolve;
        });
    };
    const bindThamKhaoModalOnce = () => {
        const closeBtn = byId("thamKhaoAppendClose");
        const cancelBtn = byId("thamKhaoAppendCancel");
        const confirmBtn = byId("thamKhaoAppendConfirm");
        const modal = byId("thamKhaoAppendModal");
        if (closeBtn && !closeBtn.dataset.bound) {
            closeBtn.dataset.bound = "1";
            closeBtn.addEventListener("click", (e) => { e.preventDefault(); closeThamKhaoAppendModal(); });
        }
        if (cancelBtn && !cancelBtn.dataset.bound) {
            cancelBtn.dataset.bound = "1";
            cancelBtn.addEventListener("click", (e) => { e.preventDefault(); closeThamKhaoAppendModal(); });
        }
        if (modal && !modal.dataset.bound) {
            modal.dataset.bound = "1";
            modal.addEventListener("click", (e) => {
                if (e.target === modal) closeThamKhaoAppendModal();
            });
        }
        if (confirmBtn && !confirmBtn.dataset.bound) {
            confirmBtn.dataset.bound = "1";
            confirmBtn.addEventListener("click", async (e) => {
                e.preventDefault();
                const box = byId("thamKhaoAppendList");
                const selected = [];
                if (box) {
                    box.querySelectorAll('input[type="checkbox"]:checked').forEach((cb) => {
                        selected.push({
                            target_url: cb.getAttribute("data-url") || "",
                            row_idx: parseInt(cb.getAttribute("data-idx"), 10),
                        });
                    });
                }
                const modalEl = byId("thamKhaoAppendModal");
                if (modalEl) {
                    modalEl.classList.remove("open");
                    modalEl.setAttribute("aria-hidden", "true");
                }
                if (_thamKhaoModalResolver) {
                    _thamKhaoModalResolver(selected);
                    _thamKhaoModalResolver = null;
                }
            });
        }
    };
    bindThamKhaoModalOnce();

    const showIlVerification = (verification) => {
        const box = byId("ilVerifyHint");
        if (!box) return;
        const v = verification && typeof verification === "object" ? verification : null;
        if (!v || v.ok) {
            box.style.display = "none";
            box.textContent = "";
            return;
        }
        const issues = Array.isArray(v.issues) ? v.issues : [];
        box.style.display = "block";
        box.textContent = issues.length
            ? `Verify sau chèn: ${issues.join(" · ")}`
            : "Verify: có cảnh báo — kiểm tra lại HTML.";
    };

    const applyInternalLinksApi = async (selectedPosts, extra = {}) => {
        const site = resolveTargetWebsite([]);
        const res = await apiFetch(`/content-ai/wp-internal-links/apply?ts=${Date.now()}`, {
            method: "POST",
            headers: authJsonHeaders(),
            body: JSON.stringify({
                content_html: getContentValue().trim(),
                target_website: site,
                selected_posts: selectedPosts,
                custom_links: [],
                current_url: _currentUrlGuess(),
                article_primary_keyword: byId("primaryKeyword")?.value?.trim() || "",
                article_secondary_keywords: byId("secondaryKeywords")?.value?.trim() || "",
                use_llm_rewrite: !!getInternalLinkUseLlm(),
                apply_mode: extra.apply_mode || "full",
                append_lead: "Tham khảo thêm:",
                confirmed_append_urls: extra.confirmed_append_urls || null,
            }),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
            throw new Error(parseApiDetail(data) || "Đi internal link thất bại.");
        }
        return data;
    };

    const applyConfirmedThamKhao = async (confirmedRows) => {
        const posts = (confirmedRows || []).map((r) => {
            const idx = Number(r.row_idx);
            if (Number.isFinite(idx)) return getInternalRowPost(idx);
            const url = String(r.target_url || "");
            const found = _internalCandidates.findIndex((c) => String(c.link || "") === url);
            if (found >= 0) return getInternalRowPost(found);
            return null;
        }).filter(Boolean);
        if (!posts.length) return { ok: false };
        const data = await applyInternalLinksApi(posts, {
            apply_mode: "append_only",
            confirmed_append_urls: posts.map((p) => p.link),
        });
        const outHtml = String(data.content_html || "").trim();
        if (outHtml) {
            setContentValue(outHtml);
            refreshPreview();
            saveFormState();
        }
        return { ok: true, data };
    };

    const applyInternalLinkForRow = async (idx) => {
        const row = _getInternalRowEl(idx);
        if (row && row.classList.contains("il-row-applied")) {
            return { ok: true, skipped: true };
        }
        const cur = getContentValue().trim();
        if (!cur) {
            return { ok: false, message: "Chưa có content để đi internal link." };
        }
        const post = getInternalRowPost(idx);
        if (!post || !post.link) {
            return { ok: false, message: "Thiếu URL bài đích hoặc anchor — kiểm tra lại dòng này." };
        }
        if (!post.anchor_text) {
            return { ok: false, message: "Nhập anchor text trước khi đi link." };
        }
        const site = resolveTargetWebsite([]);
        if (!site) {
            return { ok: false, message: "Nhập Target website để đi internal link." };
        }
        setInternalRowCircleState(idx, "loading");
        try {
            const data = await applyInternalLinksApi([post]);
            const outHtml = String(data.content_html || "").trim();
            if (outHtml) {
                if (!_ilContentBeforeApply) _ilContentBeforeApply = getContentValue();
                setContentValue(outHtml);
                refreshPreview();
                saveFormState();
                const undoBtn = byId("btnIlUndo");
                if (undoBtn) undoBtn.hidden = false;
            }
            _lastScreamingFrogTsv = String(data.screaming_frog_tsv || _lastScreamingFrogTsv || "");
            if (btnDownloadScreamingFrog) btnDownloadScreamingFrog.disabled = !_lastScreamingFrogTsv;
            const ins = Number(data.inserted_links || 0);
            const results = Array.isArray(data.link_results) ? data.link_results : [];
            const rowRes = results[0];
            const pending = (data.pending_append_offers || []).map((p) => ({
                ...p,
                row_idx: idx,
            }));
            if (ins > 0 || (rowRes && rowRes.status === "inserted")) {
                setInternalRowCircleState(idx, "done");
                showIlVerification(data.verification);
                return { ok: true, anchor: post.anchor_text, pending: [] };
            }
            if (pending.length || (rowRes && rowRes.status === "needs_confirm")) {
                setInternalRowCircleState(idx, "idle");
                return { ok: false, needsConfirm: true, pending, message: rowRes?.reason || "" };
            }
            setInternalRowCircleState(idx, "error");
            const reason = rowRes && rowRes.reason
                ? String(rowRes.reason)
                : "Không chèn được (đã có link hoặc không tìm được vị trí).";
            return { ok: false, message: reason, pending: [] };
        } catch (e) {
            setInternalRowCircleState(idx, "error");
            return { ok: false, message: String((e && e.message) || e), pending: [] };
        }
    };

    const runInternalLinksBulkFromTable = async (triggerBtn) => {
        const indices = getSelectedInternalRowIndices().filter((idx) => {
            const row = _getInternalRowEl(idx);
            return row && !row.classList.contains("il-row-applied");
        });
        if (!indices.length) {
            setHint("content", "Tick chọn ít nhất một dòng chưa chèn link.");
            setHint("internal-links", "Tick chọn bài cần đi link.");
            return;
        }
        const btn = triggerBtn || document.querySelector(".btn-il-bulk-apply");
        const oldLabel = btn ? btn.textContent : "";
        if (btn) {
            btn.disabled = true;
            btn.textContent = "Đang chèn…";
        }
        setHint("internal-links", `Đang chèn ${indices.length} internal link lần lượt…`);
        let okCount = 0;
        let failCount = 0;
        const allPending = [];
        for (let i = 0; i < indices.length; i += 1) {
            const idx = indices[i];
            setHint(
                "internal-links",
                `Đang chèn link (${i + 1}/${indices.length})…`,
            );
            const result = await applyInternalLinkForRow(idx);
            if (result && result.skipped) {
                okCount += 1;
            } else if (result && result.ok) {
                okCount += 1;
            } else if (result && result.needsConfirm && result.pending && result.pending.length) {
                allPending.push(...result.pending);
            } else {
                failCount += 1;
                if (result && result.message) {
                    setHint("content", result.message);
                }
            }
        }
        if (allPending.length && !getInternalLinkUseLlm()) {
            const dedup = [];
            const seenUrl = new Set();
            allPending.forEach((p) => {
                const u = String(p.target_url || "");
                if (!u || seenUrl.has(u)) return;
                seenUrl.add(u);
                dedup.push(p);
            });
            setHint("internal-links", "Một số link cần xác nhận dạng «Tham khảo thêm»…");
            const confirmed = await showThamKhaoAppendModal(dedup);
            if (confirmed && confirmed.length) {
                for (const c of confirmed) {
                    const ridx = Number(c.row_idx);
                    if (Number.isFinite(ridx)) setInternalRowCircleState(ridx, "loading");
                }
                try {
                    const appendData = await applyConfirmedThamKhao(confirmed);
                    if (appendData.ok) {
                        confirmed.forEach((c) => {
                            const ridx = Number(c.row_idx);
                            if (Number.isFinite(ridx)) setInternalRowCircleState(ridx, "done");
                        });
                        okCount += confirmed.length;
                    }
                } catch (err) {
                    setHint("content", String(err.message || err));
                    failCount += confirmed.length;
                }
            } else {
                failCount += dedup.length;
            }
        }
        const summary =
            failCount > 0
                ? `Xong: ${okCount} link đã chèn, ${failCount} dòng lỗi/bỏ qua.`
                : `Đã chèn ${okCount} internal link vào bài.`;
        setHint("content", summary);
        setHint("internal-links", summary);
        if (okCount > 0) {
            showIlInsertSummary(summary);
            switchIlToInsertedTab();
        }
        if (btn) {
            btn.disabled = false;
            btn.textContent = oldLabel || "Đi link";
        }
    };

    const resolveTargetWebsite = (customLinks) => {
        let site = normalizeTargetBase(String(byId("targetWebsite")?.value || "").trim())
            || String(byId("targetWebsite")?.value || "").trim();
        if (site) return site;
        const first = (customLinks || []).find((x) => x.target_url);
        if (!first) return "";
        try {
            return new URL(String(first.target_url)).origin;
        } catch (_) {
            return "";
        }
    };

    const runApplyInternalLinks = async ({ fromCustomPanel = false, triggerBtn = null } = {}) => {
        const cur = getContentValue().trim();
        if (!cur) {
            setHint("content", "Chưa có content để đi internal link.");
            if (fromCustomPanel && hintCustomLinkApply) {
                hintCustomLinkApply.textContent = "Chưa có nội dung bài trong editor.";
            }
            return;
        }
        const allCustomRows = collectCheckedCustomLinks();
        const customLinks = getValidCustomLinksForApply();
        const customInvalid = allCustomRows.filter(
            (x) => (x.target_url && !x.anchor_text) || (!x.target_url && x.anchor_text)
        );
        if (customInvalid.length) {
            const msg = "Custom link: mỗi dòng đã tick cần đủ URL và anchor (hoặc bỏ tick dòng thiếu).";
            setHint("content", msg);
            if (fromCustomPanel && hintCustomLinkApply) hintCustomLinkApply.textContent = msg;
            return;
        }
        const checked = collectWpInternalChecked();
        if (fromCustomPanel && !customLinks.length) {
            const msg =
                "Chưa có custom link hợp lệ: tick chọn dòng, nhập URL (https://...) và anchor text, rồi bấm lại «Đi Internal link».";
            setHint("content", msg);
            if (hintCustomLinkApply) hintCustomLinkApply.textContent = msg;
            return;
        }
        if (!checked.length && !customLinks.length) {
            const msg = fromCustomPanel
                ? "Thêm custom link (URL + anchor) hoặc chọn bài ở bảng WordPress phía trên."
                : "Chọn bài WordPress và/hoặc custom link (URL + anchor) để đi internal link.";
            setHint("content", msg);
            if (fromCustomPanel && hintCustomLinkApply) hintCustomLinkApply.textContent = msg;
            return;
        }
        const site = resolveTargetWebsite(customLinks);
        if (!site) {
            const msg = "Nhập Target website hoặc URL đầy đủ (https://...) trong custom link.";
            setHint("content", msg);
            if (fromCustomPanel && hintCustomLinkApply) hintCustomLinkApply.textContent = msg;
            return;
        }
        const useLlm = customLinkUseLlm ? !!customLinkUseLlm.checked : false;
        const buttons = [triggerBtn, btnApplyInternalLinks, btnApplyCustomInternalLinks].filter(Boolean);
        const oldLabels = buttons.map((b) => b.textContent);
        buttons.forEach((b) => {
            b.disabled = true;
            if (b === btnApplyCustomInternalLinks) b.textContent = "Đang viết lại & chèn link...";
            else if (b === btnApplyInternalLinks) b.textContent = "Đang đi link...";
        });
        if (previewLoading) {
            previewLoading.classList.add("show");
            if (previewLoadingText) {
                previewLoadingText.textContent = fromCustomPanel
                    ? "Đang chèn custom internal link (rule-based, tối thiểu thay đổi)..."
                    : "Đang chèn internal link (giữ nguyên bài, thêm đoạn ngắn nếu cần)...";
            }
            if (previewLoadingFill) previewLoadingFill.style.width = "35%";
            if (previewLoadingPct) previewLoadingPct.textContent = "35%";
        }
        if (hintCustomLinkApply && fromCustomPanel) {
            hintCustomLinkApply.textContent = `Đang chèn ${customLinks.length} custom link — LLM có thể mất 30–90 giây...`;
        }
        try {
            const res = await fetch(`/content-ai/wp-internal-links/apply?ts=${Date.now()}`, {
                method: "POST",
                headers: authJsonHeaders(),
                credentials: "same-origin",
                body: JSON.stringify({
                    content_html: cur,
                    target_website: site,
                    selected_posts: checked,
                    custom_links: customLinks,
                    current_url: _currentUrlGuess(),
                    article_primary_keyword: byId("primaryKeyword")?.value?.trim() || "",
                    article_secondary_keywords: byId("secondaryKeywords")?.value?.trim() || "",
                    use_llm_rewrite: useLlm,
                }),
            });
            const data = await res.json().catch(() => ({}));
            if (!res.ok) throw new Error((data && data.detail) ? data.detail : "Đi internal link thất bại.");
            const outHtml = String(data.content_html || "").trim();
            if (!outHtml) throw new Error("Không nhận được nội dung sau khi đi link.");
            if (!_ilContentBeforeApply) _ilContentBeforeApply = cur;
            setContentValue(outHtml);
            refreshPreview();
            saveFormState();
            const undoBtn = byId("btnIlUndo");
            if (undoBtn) undoBtn.hidden = false;
            _lastScreamingFrogTsv = String(data.screaming_frog_tsv || "");
            if (btnDownloadScreamingFrog) btnDownloadScreamingFrog.disabled = !_lastScreamingFrogTsv;
            renderInternalApplyResults(data.link_results);
            showIlVerification(data.verification);
            const via = data.used_llm_rewrite ? "rule + LLM tối thiểu" : "rule-based (không rewrite cả bài)";
            const ins = Number(data.inserted_links || 0);
            const skipped = (Array.isArray(data.link_results) ? data.link_results : []).filter((r) => r.status === "skipped").length;
            let msgHint = fromCustomPanel
                ? `Custom link: đã chèn ${ins} link — ${via}.`
                : `Đã chèn ${ins} internal link — ${via}.`;
            if (customLinks.length) msgHint += ` ${customLinks.length} custom.`;
            if (skipped) msgHint += ` ${skipped} bỏ qua — xem bảng bên dưới.`;
            if (ins > 0) {
                showIlInsertSummary(msgHint);
                switchIlToInsertedTab();
            }
            setHint("content", msgHint);
            if (hintCustomLinkApply) {
                hintCustomLinkApply.textContent = skipped
                    ? `Xong: ${ins} chèn, ${skipped} bỏ qua.`
                    : `Xong: đã chèn ${ins} custom internal link vào bài.`;
            }
            if (previewLoadingFill) previewLoadingFill.style.width = "100%";
            if (previewLoadingPct) previewLoadingPct.textContent = "100%";
        } catch (e) {
            const errMsg = String((e && e.message) || e);
            setHint("content", errMsg);
            if (hintCustomLinkApply) hintCustomLinkApply.textContent = errMsg.slice(0, 120);
        } finally {
            buttons.forEach((b, i) => {
                b.disabled = false;
                if (oldLabels[i]) b.textContent = oldLabels[i];
            });
            if (previewLoading) previewLoading.classList.remove("show");
        }
    };

    if (btnApplyInternalLinks) {
        btnApplyInternalLinks.addEventListener("click", () => runApplyInternalLinks({ triggerBtn: btnApplyInternalLinks }));
    }
    if (btnApplyCustomInternalLinks) {
        btnApplyCustomInternalLinks.addEventListener("click", (ev) => {
            ev.preventDefault();
            ev.stopPropagation();
            runApplyInternalLinks({ fromCustomPanel: true, triggerBtn: btnApplyCustomInternalLinks });
        });
    }
    if (btnDownloadScreamingFrog) {
        btnDownloadScreamingFrog.addEventListener("click", () => {
            if (!_lastScreamingFrogTsv) return;
            const blob = new Blob([_lastScreamingFrogTsv], { type: "text/tab-separated-values;charset=utf-8;" });
            const url = URL.createObjectURL(blob);
            const a = document.createElement("a");
            a.href = url;
            a.download = "screaming-frog-internal-links.tsv";
            document.body.appendChild(a);
            a.click();
            a.remove();
            URL.revokeObjectURL(url);
        });
    }

    // keep preview reasonably fresh without spamming
    let _previewTimer = null;
    const schedulePreview = () => {
        if (_previewTimer) clearTimeout(_previewTimer);
        _previewTimer = setTimeout(refreshPreview, 250);
    };
    document.querySelectorAll("input, textarea, select").forEach((el) => {
        if (el.id === "output") return;
        el.addEventListener("input", schedulePreview);
        el.addEventListener("change", schedulePreview);
        if (el.id === "title" || el.id === "meta" || el.id === "primaryKeyword" || el.id === "content") {
            el.addEventListener("input", schedulePublishChecklist);
            el.addEventListener("change", schedulePublishChecklist);
        }
    });
    const contentTa = byId("content");
    if (contentTa) {
        contentTa.addEventListener("input", () => {
            refreshPreview();
            syncPreviewFallback();
        });
    }
    const contentEditable = byId("contentRender");
    if (contentEditable) {
        contentEditable.addEventListener("mouseover", (e) => {
            const target = e.target;
            if (!(target instanceof Element)) return;
            const a = target.closest("a");
            if (a && contentEditable.contains(a)) {
                showLinkToolsFor(a);
            }
        });
        contentEditable.addEventListener("mousemove", (e) => {
            const target = e.target;
            if (!(target instanceof Element)) return;
            const a = target.closest("a");
            if (!a || !contentEditable.contains(a)) {
                scheduleHideLinkTools();
            } else {
                if (linkToolsHideTimer) {
                    clearTimeout(linkToolsHideTimer);
                    linkToolsHideTimer = null;
                }
            }
        });
        contentEditable.addEventListener("mouseleave", () => {
            scheduleHideLinkTools(180);
        });
        contentEditable.addEventListener("focus", rememberEditorSelection);
        contentEditable.addEventListener("keyup", rememberEditorSelection);
        contentEditable.addEventListener("mouseup", rememberEditorSelection);
        contentEditable.addEventListener("input", rememberEditorSelection);
        contentEditable.addEventListener("mousedown", (e) => {
            const target = e.target;
            if (!(target instanceof Element)) return;
            if (!target.closest(".img-action-delete")) return;
            e.preventDefault();
            e.stopPropagation();
            const fig = target.closest("figure.editor-image");
            deleteFigureElement(fig);
        });
        contentEditable.addEventListener("click", (e) => {
            const target = e.target;
            if (target && target instanceof Element) {
                if (target.closest(".img-action-delete")) return;
                const img = target.closest("img");
                if (img) {
                    selectEditorImage(img);
                    return;
                }
            }
            clearSelectedEditorFigure();
        });
        contentEditable.addEventListener("keydown", (e) => {
            if (!selectedEditorFigure) return;
            if (e.key === "Delete" || e.key === "Backspace") {
                e.preventDefault();
                deleteSelectedEditorFigure();
            }
        });
        contentEditable.addEventListener("input", () => {
            const ta = byId("content");
            if (ta) ta.value = String(contentEditable.innerHTML || "");
            try {
                if (typeof updateContentStatsFromHtml === "function") {
                    updateContentStatsFromHtml(String(contentEditable.innerHTML || ""));
                }
            } catch (_) {}
            schedulePreview();
            schedulePublishChecklist();
            scheduleSaveFormState();
        });
        contentEditable.addEventListener("keyup", () => {
            schedulePreview();
        });
        contentEditable.addEventListener("paste", () => {
            window.setTimeout(schedulePreview, 0);
        });
        contentEditable.addEventListener("click", syncBlockFormatBySelection);
        contentEditable.addEventListener("keyup", syncBlockFormatBySelection);
        contentEditable.addEventListener("mouseup", syncBlockFormatBySelection);
    }
    document.addEventListener("selectionchange", () => {
        syncBlockFormatBySelection();
        rememberEditorSelection();
    });
    refreshEditorModeUi();

    const showCaToast = (message, type) => {
        const host = byId("caToastHost");
        if (!host) return;
        const el = document.createElement("div");
        el.className = "ca-toast " + (type || "info");
        el.textContent = String(message || "");
        host.appendChild(el);
        window.setTimeout(() => {
            el.style.opacity = "0";
            el.style.transition = "opacity 0.25s";
            window.setTimeout(() => el.remove(), 280);
        }, 3200);
    };
    window.showCaToast = showCaToast;
    const _usageLabels = {
        content_ai_article: "Bài viết AI",
        content_ai_brief: "Content Brief",
        image_generate: "Ảnh AI",
        content_ai_bulk_article: "Bulk job",
        wp_publish: "WordPress Publish",
    };
    /* usage widget: static/js/content_ai/content-ai-usage.js */

    const caStickyCreate = byId("caStickyCreateContent");
    const caStickyDraft = byId("caStickyDraft");
    const caStickyPublish = byId("caStickyPublish");
    if (caStickyCreate && btnCreateContent) {
        caStickyCreate.addEventListener("click", () => btnCreateContent.click());
    }
    if (caStickyDraft && btn) {
        caStickyDraft.addEventListener("click", () => btn.click());
    }
    if (caStickyPublish && btnPublishNow) {
        caStickyPublish.addEventListener("click", () => btnPublishNow.click());
    }
    const pubCatPublish = byId("singleWpCategoryIdPublish");
    if (pubCatPublish) {
        pubCatPublish.addEventListener("change", syncSingleWpCategoryFromSelect);
    }
    const btnSeoRefresh = byId("btnSeoRefreshChecklist");
    if (btnSeoRefresh) btnSeoRefresh.addEventListener("click", () => void refreshPublishChecklist());
    if (typeof window.__caSeoAutofix !== "undefined" && window.__caSeoAutofix.init) {
        window.__caSeoAutofix.init();
    }
    const btnSeoScrollPublish = byId("btnSeoScrollPublish");
    if (btnSeoScrollPublish) {
        btnSeoScrollPublish.addEventListener("click", () => {
            if (typeof window.__caCloseSeoScorePanel === "function") window.__caCloseSeoScorePanel();
            if (typeof window.__caOpenStepModal === "function") {
                window.__caOpenStepModal("publish");
            } else {
                const el = byId("contentAiPublishBar");
                if (el) el.scrollIntoView({ behavior: "smooth", block: "start" });
            }
        });
    }

    if (btnResetForm) btnResetForm.addEventListener("click", async () => {
        try {
            const view = String(_contentAiMainView || "single");
            if (view === "projects" || view === "autoupdate") {
                const hint =
                    "Chuyển sang tab «Viết 1 bài» hoặc «Viết hàng loạt» rồi bấm Làm mới để xóa nhập liệu tab đó.";
                if (msg) msg.textContent = hint;
                showCaToast(hint, "info");
                return;
            }
            const isBulk = view === "bulk";
            const ok = window.confirm(
                isBulk
                    ? "Bạn có chắc muốn làm mới tab «Viết hàng loạt»? Danh sách từ khóa và form bulk (kể cả bản nháp trên trình duyệt) sẽ bị xóa."
                    : "Bạn có chắc muốn làm mới tab «Viết 1 bài»? Toàn bộ ô nhập và bản nháp trên trình duyệt của tab này sẽ bị xóa."
            );
            if (!ok) return;
            if (isBulk) {
                resetBulkWriteForm();
                scheduleSaveBulkState();
                if (msg) msg.textContent = "Đã làm mới tab «Viết hàng loạt».";
                showCaToast("Đã làm mới form Viết hàng loạt.", "success");
            } else {
                resetContentAiSingleForm();
                try {
                    await refreshProjects(true);
                } catch (_) {}
                if (msg) msg.textContent = "Đã làm mới tab «Viết 1 bài».";
                showCaToast("Đã làm mới form Viết 1 bài.", "success");
            }
        } catch (e) {
            showCaToast(String((e && e.message) || "Không thể làm mới form."), "error");
        }
    });
