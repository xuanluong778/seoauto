/**
 * Chatbot AI — Tab Chat (mặc định) + workflow tabs
 */
(function () {
    var ROOT_ID = "digiseoChatbotRoot";
    var SESSION_KEY = "digiseo_chat_session";
    var AVATAR = "/static/img/digiseo-chatbot-avatar.png";
    var CHAT_TAB_ID = "chat";
    var TAG_DIV = "d" + "iv";
    var activeTab = CHAT_TAB_ID;
    var activePoll = null;
    var sessionId = "";
    var workflowState = {};
    var chatState = {
        history: [],
        welcomeShown: false,
        draftInput: "",
        loadingCardId: null,
        lastUserMessage: "",
        pendingRetry: null,
    };
    var voiceRecognition = null;
    var isListening = false;

    var FALLBACK_PROMPTS = [
        { id: "pricing", label: "Giá phần mềm Seoauto bao nhiêu?" },
        { id: "credit", label: "Chat tab có trừ credit không?" },
        { id: "seo_article", label: "Làm sao viết bài SEO bằng AI?" },
        { id: "seo_score", label: "Cách chấm điểm SEO cho URL?" },
        { id: "audit", label: "Audit technical website như thế nào?" },
        { id: "keyword", label: "Research từ khóa trên Seoauto?" },
        { id: "kb", label: "Knowledge Base dùng để làm gì?" },
        { id: "wordpress", label: "Xuất bản bài lên WordPress?" },
        { id: "api_error", label: "API key bị lỗi thì xử lý sao?" },
    ];

    var WRITE_INTENTS = {
        quick_keyword_article: true,
        keyword_cluster_to_article: true,
    };

    var WRITE_TONE_OPTIONS = [
        "Chuyên nghiệp",
        "Thân thiện",
        "Chuyên gia",
        "Bán hàng",
        "Chia sẻ kinh nghiệm",
        "Trung lập",
        "Tự nhiên",
    ];

    var WRITE_WORD_COUNT_PRESETS = ["800", "1000", "1500", "2000"];
    var WRITE_WORD_COUNT_MIN = 300;
    var WRITE_WORD_COUNT_MAX = 5000;

    var BUSINESS_VERTICAL_OPTIONS = [
        { id: "", label: "— Chọn ngành (nếu từ khóa mơ hồ) —" },
        { id: "seo_entity", label: "SEO / Entity / Marketing" },
        { id: "it_repair", label: "Sửa máy tính / IT" },
        { id: "web_design", label: "Thiết kế web / Phần mềm" },
        { id: "healthcare", label: "Y tế / Sức khỏe" },
        { id: "education", label: "Giáo dục / Đào tạo" },
        { id: "real_estate", label: "Bất động sản" },
        { id: "legal", label: "Pháp lý / Tư vấn" },
        { id: "other", label: "Khác" },
    ];

    var FALLBACK_TABS = [
        {
            id: "write",
            label: "Viết bài SEO",
            workflows: [
                {
                    id: "quick_keyword_article",
                    title: "Viết nhanh theo từ khóa",
                    description: "Chỉ nhập từ khóa — AI tạo title, meta, outline và viết bài (credit thấp).",
                },
                {
                    id: "keyword_cluster_to_article",
                    title: "Viết bài chuyên sâu",
                    description: "Research, gom cụm, từ khóa phụ và viết bài SEO chuẩn (credit đầy đủ).",
                },
            ],
        },
        {
            id: "seo_score",
            label: "SEO Score",
            workflows: [
                {
                    id: "url_seo_scoreboard",
                    title: "Chấm điểm URL",
                    description: "Nhập URL + từ khóa chính — crawl và phân tích SEO Onpage.",
                },
                {
                    id: "content_seo_score",
                    title: "Chấm điểm nội dung",
                    description: "Dán nội dung bài viết + từ khóa — phân tích SEO Core 30 yếu tố.",
                },
            ],
        },
        {
            id: "technical",
            label: "Technical",
            workflows: [
                {
                    id: "technical_quick_audit",
                    title: "Audit nhanh",
                    description: "Nhập URL — crawl nhanh, kiểm tra lỗi technical cơ bản.",
                },
                {
                    id: "technical_deep_audit",
                    title: "Audit chuyên sâu",
                    description: "Nhập URL + số trang — phân tích technical chi tiết, lưu báo cáo.",
                },
                {
                    id: "technical_single_url",
                    title: "Kiểm tra URL riêng lẻ",
                    description: "Nhập 1 URL — kiểm tra status, index, canonical, robots, sitemap…",
                },
            ],
        },
        {
            id: "research",
            label: "Từ khóa",
            workflows: [
                {
                    id: "keyword_research",
                    title: "Research từ khóa",
                    description: "Mở rộng từ khóa liên quan theo quốc gia, ngôn ngữ và số lượng.",
                },
                {
                    id: "keyword_research_cluster",
                    title: "Research + gom nhóm",
                    description: "Research, gom cụm, gợi ý title/outline và chuyển sang Viết bài SEO.",
                },
            ],
        },
    ];

    function esc(s) {
        var d = document.createElement(TAG_DIV);
        d.textContent = s;
        return d.innerHTML;
    }

    function formatReply(text) {
        return esc(String(text || "")).replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
    }

    function pagePath() {
        return (window.location && window.location.pathname) || "/";
    }

    function getToken() {
        try {
            return sessionStorage.getItem("seo_token") || "";
        } catch (_) {
            return "";
        }
    }

    function authHeaders(extra) {
        var headers = extra || { "Content-Type": "application/json" };
        var token = getToken();
        if (token) headers.Authorization = "Bearer " + token;
        return headers;
    }

    function getSessionId() {
        if (sessionId) return sessionId;
        try {
            sessionId = sessionStorage.getItem(SESSION_KEY) || "";
            if (!sessionId) {
                sessionId = "s_" + Date.now().toString(36) + "_" + Math.random().toString(36).slice(2, 10);
                sessionStorage.setItem(SESSION_KEY, sessionId);
            }
        } catch (_) {
            sessionId = "s_anon_" + Date.now();
        }
        return sessionId;
    }

    async function apiFetch(paths, options) {
        var res = null;
        for (var i = 0; i < paths.length; i++) {
            try {
                res = await fetch(paths[i], options);
                if (res.status !== 404) break;
            } catch (e) {
                if (i === paths.length - 1) throw e;
            }
        }
        if (!res) throw new Error("Không kết nối được máy chủ.");
        return res;
    }

    var TAB_RUNNING_MESSAGES = {
        write: "Đang thực hiện viết bài SEO…",
        seo_score: "Đang chấm điểm SEO…",
        technical: "Đang kiểm tra technical…",
        research: "Đang research từ khóa…",
    };

    var WF_STEP_PRESETS = {
        chat: [
            { id: "send", label: "Gửi tin nhắn" },
            { id: "reply", label: "AI đang trả lời" },
        ],
        preview_outline: [
            { id: "validate", label: "Kiểm tra thông tin" },
            { id: "outline", label: "Tạo outline theo SEO Score" },
            { id: "credit", label: "Ước tính credit" },
        ],
        prepare: [
            { id: "validate", label: "Kiểm tra thông tin" },
            { id: "credit", label: "Ước tính credit" },
        ],
        confirm_start: [
            { id: "confirm", label: "Xác nhận workflow" },
            { id: "start", label: "Khởi chạy xử lý" },
        ],
    };

    function defaultWorkflowState() {
        return {
            phase: "idle",
            tabRevealed: false,
            workflowId: null,
            intent: null,
            credits: null,
            prepare: null,
            planning: null,
            formParams: null,
            balance: null,
            sufficient: null,
            progress: null,
            result: null,
            loadingCardId: null,
            returnPhase: null,
            errorMessage: null,
            pendingRetry: null,
        };
    }

    function resetWorkflowState() {
        var st = defaultWorkflowState();
        st.phase = "cards";
        st.tabRevealed = true;
        return st;
    }

    function getRunningMessage(tabId, st) {
        var progress = st && st.progress ? st.progress : [];
        for (var i = 0; i < progress.length; i++) {
            if (String(progress[i].status || "") === "running") {
                var label = String(progress[i].label || "").trim();
                if (label) return label;
            }
        }
        return TAB_RUNNING_MESSAGES[tabId] || "Đang xử lý…";
    }

    function renderRunningBanner(container, tabId, st) {
        container.innerHTML =
            '<div class="gcb-running-banner" role="status" aria-live="polite">' +
            '<span class="gcb-running-spinner" aria-hidden="true"></span>' +
            "<span>" +
            esc(getRunningMessage(tabId, st)) +
            "</span></div>";
    }

    function normalizeProgressSteps(steps) {
        return (steps || []).map(function (step) {
            return {
                id: String(step.id || ""),
                label: String(step.label || step.id || ""),
                status: String(step.status || "pending"),
            };
        });
    }

    function presetSteps(presetKey, runningStepId) {
        var preset = WF_STEP_PRESETS[presetKey] || [];
        var runIdx = -1;
        if (runningStepId) {
            for (var i = 0; i < preset.length; i++) {
                if (preset[i].id === runningStepId) {
                    runIdx = i;
                    break;
                }
            }
        }
        return preset.map(function (s, idx) {
            var status = "pending";
            if (runIdx >= 0) {
                if (idx < runIdx) status = "done";
                else if (idx === runIdx) status = "running";
            } else if (idx === 0 && preset.length) {
                status = "running";
            }
            return { id: s.id, label: s.label, status: status };
        });
    }

    function markAllStepsDone(steps) {
        return normalizeProgressSteps(steps).map(function (s) {
            return { id: s.id, label: s.label, status: "done" };
        });
    }

    function renderProgressStepsHtml(steps) {
        var html = '<ul class="gcb-wf-progress">';
        normalizeProgressSteps(steps).forEach(function (step) {
            var st = step.status || "pending";
            html +=
                '<li class="gcb-wf-progress-item gcb-wf-progress-item--' +
                esc(st) +
                '">' +
                '<span class="gcb-wf-progress-dot" aria-hidden="true"></span>' +
                "<span>" +
                esc(step.label) +
                "</span></li>";
        });
        html += "</ul>";
        return html;
    }

    function buildLoadingCardHtml(message, steps) {
        return (
            '<div class="gcb-wf-card gcb-wf-card--loading" data-gcb-wf-card="loading" role="status" aria-live="polite">' +
            '<div class="gcb-wf-card-head">' +
            '<span class="gcb-running-spinner" aria-hidden="true"></span>' +
            '<span class="gcb-wf-card-title">' +
            esc(message || "Đang xử lý…") +
            "</span></div>" +
            renderProgressStepsHtml(steps) +
            "</div>"
        );
    }

    function buildErrorCardHtml(message) {
        return (
            '<div class="gcb-wf-card gcb-wf-card--error" data-gcb-wf-card="error" role="alert">' +
            '<div class="gcb-wf-card-head gcb-wf-card-head--error">' +
            '<span class="gcb-wf-error-ico" aria-hidden="true">!</span>' +
            '<span class="gcb-wf-card-title">Không thể hoàn thành</span></div>' +
            '<p class="gcb-wf-error-msg">' +
            esc(message || "Đã xảy ra lỗi.") +
            "</p>" +
            '<div class="gcb-wf-card-actions">' +
            '<button type="button" class="gcb-btn gcb-btn--primary" data-gcb-wf-retry>Thử lại</button>' +
            "</div></div>"
        );
    }

    function ensureStageSection(tabId) {
        if (tabId === CHAT_TAB_ID) return document.getElementById("digiseoChatbotMessages");
        var panel = document.querySelector('[data-gcb-panel="' + tabId + '"]');
        if (!panel) return null;
        var stage = panel.querySelector('[data-gcb-section="stage"]');
        if (!stage) {
            stage = document.createElement("section");
            stage.className = "gcb-section gcb-section--stage";
            stage.dataset.gcbSection = "stage";
            stage.hidden = true;
            panel.appendChild(stage);
        }
        return stage;
    }

    function getWorkflowCardEl(tabId, cardId) {
        if (tabId === CHAT_TAB_ID) {
            if (!cardId) return null;
            return document.querySelector('[data-gcb-wf-card-id="' + cardId + '"]');
        }
        var stage = ensureStageSection(tabId);
        return stage ? stage.querySelector("[data-gcb-wf-card]") : null;
    }

    function setPanelLoading(tabId, loading) {
        if (tabId === CHAT_TAB_ID) return;
        var panel = document.querySelector('[data-gcb-panel="' + tabId + '"]');
        if (panel) panel.classList.toggle("gcb-panel--loading", !!loading);
    }

    function setWorkflowBusy(tabId, busy) {
        if (tabId === CHAT_TAB_ID) {
            setChatSending(busy);
            return;
        }
        var panel = document.querySelector('[data-gcb-panel="' + tabId + '"]');
        if (!panel) return;
        panel.querySelectorAll("button, input, select, textarea").forEach(function (el) {
            if (el.closest(".gcb-wf-card")) return;
            el.disabled = !!busy;
        });
    }

    function bindWorkflowRetry(container, onRetry) {
        if (!container || !onRetry) return;
        var btn = container.querySelector("[data-gcb-wf-retry]");
        if (!btn) return;
        btn.addEventListener("click", function () {
            onRetry();
        });
    }

    function showWorkflowLoading(opts) {
        opts = opts || {};
        var tabId = opts.tabId || activeTab;
        var message = opts.message || TAB_RUNNING_MESSAGES[tabId] || "Đang xử lý…";
        var steps = opts.steps || presetSteps("prepare", null);
        var cardId = opts.cardId || "gcb-wf-" + tabId + "-" + Date.now();

        if (tabId === CHAT_TAB_ID) {
            var box = document.getElementById("digiseoChatbotMessages");
            if (!box) return null;
            var row = document.createElement(TAG_DIV);
            row.className = "digiseo-chatbot-msg-row";
            row.dataset.gcbWfCardId = cardId;
            var img = document.createElement("img");
            img.className = "digiseo-chatbot-msg-ico";
            img.src = AVATAR;
            img.alt = "";
            img.width = 28;
            img.height = 28;
            row.appendChild(img);
            var wrap = document.createElement(TAG_DIV);
            wrap.className = "digiseo-chatbot-msg digiseo-chatbot-msg--bot";
            wrap.innerHTML = buildLoadingCardHtml(message, steps);
            row.appendChild(wrap);
            box.appendChild(row);
            box.scrollTop = box.scrollHeight;
            chatState.loadingCardId = cardId;
        } else {
            var stage = ensureStageSection(tabId);
            if (!stage) return null;
            stage.hidden = false;
            stage.innerHTML = buildLoadingCardHtml(message, steps);
            var st = getWorkflowState(tabId);
            if (st) st.loadingCardId = cardId;
            setPanelLoading(tabId, true);
        }

        setWorkflowBusy(tabId, true);
        return cardId;
    }

    function updateWorkflowProgress(opts) {
        opts = opts || {};
        var tabId = opts.tabId || activeTab;
        var cardId = opts.cardId || (tabId === CHAT_TAB_ID ? chatState.loadingCardId : getWorkflowState(tabId) && getWorkflowState(tabId).loadingCardId);
        var message = opts.message;
        var steps = opts.steps;

        var cardEl = null;
        if (tabId === CHAT_TAB_ID) {
            cardEl = document.querySelector('[data-gcb-wf-card-id="' + cardId + '"] [data-gcb-wf-card="loading"]');
        } else {
            var stage = ensureStageSection(tabId);
            cardEl = stage && stage.querySelector('[data-gcb-wf-card="loading"]');
        }
        if (!cardEl) return;

        if (message) {
            var title = cardEl.querySelector(".gcb-wf-card-title");
            if (title) title.textContent = message;
        }
        if (steps) {
            var oldList = cardEl.querySelector(".gcb-wf-progress");
            if (oldList) {
                var tmp = document.createElement(TAG_DIV);
                tmp.innerHTML = renderProgressStepsHtml(steps);
                oldList.replaceWith(tmp.firstChild);
            }
        }
    }

    function hideWorkflowLoading(opts) {
        opts = opts || {};
        var tabId = opts.tabId || activeTab;
        var cardId = opts.cardId || (tabId === CHAT_TAB_ID ? chatState.loadingCardId : getWorkflowState(tabId) && getWorkflowState(tabId).loadingCardId);

        if (tabId === CHAT_TAB_ID) {
            var row = document.querySelector('[data-gcb-wf-card-id="' + cardId + '"]');
            if (row && row.parentNode) row.parentNode.removeChild(row);
            chatState.loadingCardId = null;
        } else {
            var stage = ensureStageSection(tabId);
            if (stage) {
                stage.hidden = true;
                stage.innerHTML = "";
            }
            var st = getWorkflowState(tabId);
            if (st) st.loadingCardId = null;
            setPanelLoading(tabId, false);
        }

        setWorkflowBusy(tabId, false);
    }

    function showWorkflowError(opts) {
        opts = opts || {};
        var tabId = opts.tabId || activeTab;
        var message = opts.message || "Đã xảy ra lỗi.";
        var onRetry = opts.onRetry;

        hideWorkflowLoading({ tabId: tabId, cardId: opts.cardId });

        if (tabId === CHAT_TAB_ID) {
            var box = document.getElementById("digiseoChatbotMessages");
            if (!box) return;
            var row = document.createElement(TAG_DIV);
            row.className = "digiseo-chatbot-msg-row";
            var img = document.createElement("img");
            img.className = "digiseo-chatbot-msg-ico";
            img.src = AVATAR;
            img.alt = "";
            img.width = 28;
            img.height = 28;
            row.appendChild(img);
            var wrap = document.createElement(TAG_DIV);
            wrap.className = "digiseo-chatbot-msg digiseo-chatbot-msg--bot";
            wrap.innerHTML = buildErrorCardHtml(message);
            row.appendChild(wrap);
            box.appendChild(row);
            bindWorkflowRetry(wrap, onRetry);
            box.scrollTop = box.scrollHeight;
            chatState.pendingRetry = onRetry || null;
            return;
        }

        var st = getWorkflowState(tabId);
        if (st) {
            st.phase = "error";
            st.errorMessage = message;
            if (onRetry && !st.pendingRetry) st.pendingRetry = onRetry;
            if (!st.returnPhase) st.returnPhase = "form";
        }
        var stage = ensureStageSection(tabId);
        if (!stage) return;
        stage.hidden = false;
        stage.innerHTML = buildErrorCardHtml(message);
        bindWorkflowRetry(stage, function () {
            runWorkflowRetry(tabId);
        });
        setPanelLoading(tabId, false);
        setWorkflowBusy(tabId, false);
        renderTabPanel(tabId);
    }

    function showWorkflowResult(tabId, renderFn) {
        hideWorkflowLoading({ tabId: tabId });
        setPanelLoading(tabId, false);
        var st = getWorkflowState(tabId);
        if (st) {
            st.errorMessage = null;
            st.pendingRetry = null;
            st.returnPhase = null;
        }
        if (typeof renderFn === "function") renderFn();
    }

    function runWorkflowRetry(tabId) {
        var st = getWorkflowState(tabId);
        if (!st || !st.pendingRetry) return;
        var stage = ensureStageSection(tabId);
        if (stage) {
            stage.hidden = true;
            stage.innerHTML = "";
        }
        st.phase = st.returnPhase || "form";
        st.errorMessage = null;
        var fn = st.pendingRetry;
        st.pendingRetry = null;
        renderTabPanel(tabId);
        var form = resolveFormElement(tabId, null);
        if (form && st.formParams && isWriteIntent(st.intent)) {
            prefillWriteForm(form, st.formParams);
        }
        fn();
    }

    function getWorkflowState(tabId) {
        if (tabId === CHAT_TAB_ID) return null;
        if (!workflowState[tabId]) workflowState[tabId] = defaultWorkflowState();
        return workflowState[tabId];
    }

    function isChatTabActive() {
        return activeTab === CHAT_TAB_ID;
    }

    function isWriteIntent(intent) {
        return !!WRITE_INTENTS[String(intent || "")];
    }

    function setOpen(open) {
        var root = document.getElementById(ROOT_ID);
        if (!root) return;
        root.classList.toggle("is-open", open);
        root.setAttribute("aria-hidden", open ? "false" : "true");
        if (open) {
            if (!activeTab) switchTab(CHAT_TAB_ID);
            if (isChatTabActive()) {
                var input = document.getElementById("digiseoChatbotInput");
                if (input) setTimeout(function () { input.focus(); }, 120);
            }
        }
    }

    function updateGuestNoticeForTab() {
        var el = document.getElementById("gcbGuest");
        var isGuest = !getToken();
        if (isChatTabActive()) {
            if (el) el.hidden = true;
            return;
        }
        if (el) el.hidden = !isGuest;
        if (isGuest) {
            document.querySelectorAll('[data-gcb-panel]:not([data-gcb-panel="' + CHAT_TAB_ID + '"])').forEach(function (p) {
                p.hidden = true;
            });
        }
    }

    function setChatFooterVisible(show) {
        var foot = document.getElementById("digiseoChatbotFoot");
        var root = document.getElementById(ROOT_ID);
        if (foot) foot.hidden = !show;
        if (root) root.classList.toggle("gcb-tab-chat-active", !!show);
    }

    function saveChatDraft() {
        var input = document.getElementById("digiseoChatbotInput");
        if (input) chatState.draftInput = input.value;
    }

    function restoreChatDraft() {
        var input = document.getElementById("digiseoChatbotInput");
        if (input) input.value = chatState.draftInput || "";
    }

    function showGuestNotice(show) {
        if (isChatTabActive()) {
            updateGuestNoticeForTab();
            return;
        }
        var el = document.getElementById("gcbGuest");
        var panels = document.getElementById("gcbPanels");
        if (el) el.hidden = !show;
        if (panels && show) {
            document.querySelectorAll('[data-gcb-panel]:not([data-gcb-panel="' + CHAT_TAB_ID + '"])').forEach(function (p) {
                p.hidden = true;
            });
        }
        updateGuestNoticeForTab();
    }

    function appendChatMsg(role, text, extraClass, suggestTab, suggestLabel) {
        var box = document.getElementById("digiseoChatbotMessages");
        if (!box) return null;
        var row = document.createElement(TAG_DIV);
        row.className =
            "digiseo-chatbot-msg-row" + (role === "user" ? " digiseo-chatbot-msg-row--user" : "");

        if (role !== "user") {
            var img = document.createElement("img");
            img.className = "digiseo-chatbot-msg-ico";
            img.src = AVATAR;
            img.alt = "";
            img.width = 28;
            img.height = 28;
            row.appendChild(img);
        }

        var el = document.createElement(TAG_DIV);
        el.className =
            "digiseo-chatbot-msg digiseo-chatbot-msg--" +
            (role === "user" ? "user" : "bot") +
            (extraClass ? " " + extraClass : "");
        if (role === "user") {
            el.textContent = text;
        } else {
            el.innerHTML = formatReply(text);
        }
        row.appendChild(el);
        if (role !== "user" && suggestTab) {
            var actions = document.createElement(TAG_DIV);
            actions.className = "gcb-chat-suggest";
            var btn = document.createElement("button");
            btn.type = "button";
            btn.className = "gcb-btn gcb-btn--primary gcb-btn--compact";
            btn.textContent = "Chuyển sang " + (suggestLabel || suggestTab);
            btn.addEventListener("click", function () {
                switchTab(String(suggestTab));
            });
            actions.appendChild(btn);
            row.appendChild(actions);
        }
        box.appendChild(row);
        box.scrollTop = box.scrollHeight;
        return el;
    }

    function setChatSending(busy) {
        var btn = document.getElementById("digiseoChatbotSend");
        var input = document.getElementById("digiseoChatbotInput");
        var mic = document.getElementById("digiseoChatbotMic");
        if (btn) btn.disabled = busy;
        if (input) input.disabled = busy;
        if (mic && isListening) return;
        if (mic) mic.disabled = busy;
        document.querySelectorAll(".digiseo-chatbot-quick-btn").forEach(function (b) {
            b.disabled = busy;
        });
    }

    async function sendChatMessage(textOverride) {
        var input = document.getElementById("digiseoChatbotInput");
        var text = (textOverride != null ? String(textOverride) : input && input.value) || "";
        text = text.trim();
        if (!text) return;
        if (chatState.loadingCardId) return;
        if (input && textOverride == null) input.value = "";

        appendChatMsg("user", text);
        chatState.history.push({ role: "user", content: text });
        chatState.lastUserMessage = text;

        var cardId = showWorkflowLoading({
            tabId: CHAT_TAB_ID,
            message: "Đang trả lời…",
            steps: presetSteps("chat", "send"),
        });

        try {
            updateWorkflowProgress({
                tabId: CHAT_TAB_ID,
                cardId: cardId,
                steps: presetSteps("chat", "reply"),
                message: "AI đang trả lời…",
            });
            var res = await apiFetch(["/api/chatbot/message", "/chatbot/message"], {
                method: "POST",
                headers: authHeaders(),
                body: JSON.stringify({
                    message: text,
                    history: chatState.history.slice(0, -1),
                    page_path: pagePath(),
                    session_id: getSessionId(),
                    chat_mode: true,
                }),
            });
            var data = await res.json().catch(function () {
                return {};
            });
            if (!res.ok) {
                var detail = data.detail;
                if (typeof detail === "object" && detail && detail.message) detail = detail.message;
                if (Array.isArray(detail)) {
                    detail = detail.map(function (x) { return x.msg || x; }).join(", ");
                }
                throw new Error(detail || data.message || "HTTP " + res.status);
            }
            if (data.session_id) {
                sessionId = data.session_id;
                try {
                    sessionStorage.setItem(SESSION_KEY, sessionId);
                } catch (_) {}
            }
            var reply = String(data.reply || "").trim() || "Không nhận được phản hồi.";
            var suggestTab = data.suggest_tab || null;
            var suggestLabel = data.suggest_tab_label || null;
            updateWorkflowProgress({
                tabId: CHAT_TAB_ID,
                cardId: cardId,
                steps: markAllStepsDone(presetSteps("chat", "reply")),
            });
            hideWorkflowLoading({ tabId: CHAT_TAB_ID, cardId: cardId });
            appendChatMsg("bot", reply, null, suggestTab, suggestLabel);
            chatState.history.push({ role: "assistant", content: reply });
            if (chatState.history.length > 24) chatState.history = chatState.history.slice(-24);
            chatState.pendingRetry = null;
        } catch (err) {
            var errMsg = err && err.message ? err.message : String(err);
            showWorkflowError({
                tabId: CHAT_TAB_ID,
                cardId: cardId,
                message: errMsg,
                onRetry: function () {
                    if (chatState.lastUserMessage) sendChatMessage(chatState.lastUserMessage);
                },
            });
        } finally {
            setChatSending(false);
        }
    }

    function renderQuickPrompts(prompts) {
        var wrap = document.getElementById("digiseoChatbotQuick");
        if (!wrap) return;
        var list = prompts && prompts.length ? prompts : FALLBACK_PROMPTS;
        wrap.innerHTML = "";
        list.forEach(function (p) {
            var btn = document.createElement("button");
            btn.type = "button";
            btn.className = "digiseo-chatbot-quick-btn";
            if (p.id === "pricing") btn.className += " digiseo-chatbot-quick-btn--pricing";
            btn.textContent = p.label || p.id;
            btn.addEventListener("click", function () {
                closeQuickPopup();
                sendChatMessage(p.label || "");
            });
            wrap.appendChild(btn);
        });
    }

    async function loadQuickPrompts() {
        try {
            var res = await apiFetch(["/api/chatbot/prompts", "/chatbot/prompts"], { headers: authHeaders({}) });
            if (!res.ok) throw new Error("prompts " + res.status);
            var data = await res.json();
            renderQuickPrompts(data.prompts || FALLBACK_PROMPTS);
        } catch (_) {
            renderQuickPrompts(FALLBACK_PROMPTS);
        }
    }

    function closeQuickPopup() {
        var popup = document.getElementById("digiseoChatbotQuickPopup");
        var toggle = document.getElementById("digiseoChatbotQuickToggle");
        if (popup) {
            popup.hidden = true;
            popup.classList.remove("is-open");
        }
        if (toggle) {
            toggle.setAttribute("aria-expanded", "false");
            toggle.textContent = "Hiển thị câu hỏi nhanh";
        }
    }

    function openQuickPopup() {
        var popup = document.getElementById("digiseoChatbotQuickPopup");
        var toggle = document.getElementById("digiseoChatbotQuickToggle");
        if (popup) {
            popup.hidden = false;
            popup.classList.add("is-open");
        }
        if (toggle) {
            toggle.setAttribute("aria-expanded", "true");
            toggle.textContent = "Ẩn câu hỏi nhanh";
        }
    }

    function toggleQuickPopup() {
        var popup = document.getElementById("digiseoChatbotQuickPopup");
        if (!popup) return;
        if (popup.hidden) openQuickPopup();
        else closeQuickPopup();
    }

    function stopVoiceInput() {
        isListening = false;
        var mic = document.getElementById("digiseoChatbotMic");
        if (mic) {
            mic.classList.remove("is-listening");
            mic.setAttribute("aria-pressed", "false");
            mic.setAttribute("aria-label", "Ghi âm giọng nói");
        }
    }

    function voiceInputErrorMessage(code) {
        if (code === "not-allowed" || code === "service-not-allowed") {
            return "Không thể dùng micro — vui lòng cho phép quyền micro trên trình duyệt rồi tải lại trang.";
        }
        if (code === "audio-capture") {
            return "Không tìm thấy micro hoặc micro đang bị ứng dụng khác dùng.";
        }
        if (code === "network") {
            return "Lỗi mạng khi nhận dạng giọng nói. Kiểm tra kết nối internet rồi thử lại.";
        }
        if (code === "no-speech" || code === "aborted") {
            return "";
        }
        return code ? "Lỗi ghi âm (" + code + "). Hãy thử lại hoặc nhập tay." : "";
    }

    function isVoiceInputSupported() {
        var SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
        return !!(SpeechRecognition && window.isSecureContext);
    }

    function initVoiceInput() {
        var SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
        if (!SpeechRecognition || !window.isSecureContext) return null;
        var rec = new SpeechRecognition();
        rec.lang = "vi-VN";
        rec.interimResults = true;
        rec.continuous = false;
        rec.maxAlternatives = 1;
        rec.onresult = function (event) {
            var transcript = "";
            for (var i = event.resultIndex; i < event.results.length; i++) {
                transcript += event.results[i][0].transcript;
            }
            var input = document.getElementById("digiseoChatbotInput");
            if (input) {
                input.value = transcript.trim();
                input.dispatchEvent(new Event("input", { bubbles: true }));
            }
        };
        rec.onend = function () {
            stopVoiceInput();
            voiceRecognition = null;
        };
        rec.onerror = function (event) {
            var msg = voiceInputErrorMessage(event && event.error ? event.error : "");
            stopVoiceInput();
            voiceRecognition = null;
            if (msg) alert(msg);
        };
        return rec;
    }

    function toggleVoiceInput() {
        if (!isVoiceInputSupported()) {
            if (!window.isSecureContext) {
                alert("Ghi âm giọng nói cần HTTPS. Vui lòng mở site qua https://.");
            } else {
                alert("Trình duyệt không hỗ trợ ghi âm giọng nói. Vui lòng dùng Chrome hoặc Edge.");
            }
            return;
        }
        if (isListening && voiceRecognition) {
            try {
                voiceRecognition.stop();
            } catch (_) {}
            stopVoiceInput();
            voiceRecognition = null;
            return;
        }
        voiceRecognition = initVoiceInput();
        if (!voiceRecognition) {
            alert("Không thể khởi tạo ghi âm giọng nói. Hãy thử lại.");
            return;
        }
        var mic = document.getElementById("digiseoChatbotMic");
        try {
            isListening = true;
            if (mic) {
                mic.classList.add("is-listening");
                mic.setAttribute("aria-pressed", "true");
                mic.setAttribute("aria-label", "Đang ghi âm — bấm để dừng");
            }
            voiceRecognition.start();
        } catch (_) {
            stopVoiceInput();
            voiceRecognition = null;
            alert("Không thể bật micro. Hãy cho phép quyền micro trên trình duyệt.");
        }
    }

    function initChatWelcome() {
        if (chatState.welcomeShown) return;
        chatState.welcomeShown = true;
        appendChatMsg(
            "bot",
            "Xin chào! Đây là tab **Chat** — hỏi đáp FAQ, bảng giá và hướng dẫn Seoauto (không trừ credit).\n\n" +
                "Muốn **viết bài**, **chấm điểm SEO**, **audit technical** hoặc **research từ khóa**, chọn tab tương ứng phía trên."
        );
    }

    function bindChatUi() {
        var foot = document.getElementById("digiseoChatbotFoot");
        if (foot && foot.dataset.chatBound === "1") return;
        if (foot) foot.dataset.chatBound = "1";

        var sendBtn = document.getElementById("digiseoChatbotSend");
        var input = document.getElementById("digiseoChatbotInput");
        var mic = document.getElementById("digiseoChatbotMic");
        var quickToggle = document.getElementById("digiseoChatbotQuickToggle");
        var quickClose = document.getElementById("digiseoChatbotQuickClose");

        if (sendBtn) sendBtn.addEventListener("click", function () { sendChatMessage(); });
        if (input) {
            input.addEventListener("keydown", function (e) {
                if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    sendChatMessage();
                }
            });
        }
        if (mic) mic.addEventListener("click", toggleVoiceInput);
        if (quickToggle) quickToggle.addEventListener("click", toggleQuickPopup);
        if (quickClose) quickClose.addEventListener("click", closeQuickPopup);

        renderQuickPrompts(FALLBACK_PROMPTS);
        loadQuickPrompts().then(function () {
            openQuickPopup();
        });
    }

    function imageCountForWc(wc) {
        var n = Number(wc) || 0;
        if (n >= 2000) return 4;
        if (n >= 1500) return 3;
        if (n >= 1000) return 2;
        if (n >= 500) return 1;
        return 0;
    }

    function getWriteWordCountField(form) {
        if (!form) return { field: null, select: null, input: null };
        return {
            field: form.querySelector("[data-gcb-wc-field]"),
            select: form.querySelector("[data-gcb-wc-select]"),
            input: form.querySelector("[data-gcb-wc-input]"),
        };
    }

    function applyWriteWordCountMode(form, isCustom, customValue) {
        var parts = getWriteWordCountField(form);
        if (!parts.select || !parts.input) return;
        if (isCustom) {
            if (parts.field) parts.field.classList.add("is-custom");
            parts.input.hidden = false;
            parts.input.disabled = false;
            if (customValue != null && customValue !== "") {
                parts.input.value = String(customValue);
            } else if (!parts.input.value) {
                parts.input.value = "1500";
            }
        } else {
            if (parts.field) parts.field.classList.remove("is-custom");
            parts.input.hidden = true;
            parts.input.disabled = true;
            parts.input.value = "";
            parts.input.classList.remove("gcb-input--invalid");
        }
    }

    function prefillWriteForm(form, params) {
        if (!form || !params) return;
        var pk = form.querySelector('[name="primary_keyword"]');
        if (pk && params.primary_keyword) pk.value = params.primary_keyword;
        var wc = Number(params.word_count) || 1500;
        var parts = getWriteWordCountField(form);
        if (parts.select && parts.input) {
            var preset = String(wc);
            if (WRITE_WORD_COUNT_PRESETS.indexOf(preset) >= 0) {
                parts.select.value = preset;
                applyWriteWordCountMode(form, false);
            } else {
                parts.select.value = "custom";
                var clamped = Math.max(
                    WRITE_WORD_COUNT_MIN,
                    Math.min(WRITE_WORD_COUNT_MAX, wc)
                );
                applyWriteWordCountMode(form, true, clamped);
            }
        }
        var img = form.querySelector('[name="image_source"]');
        if (img && params.image_source) img.value = params.image_source;
        var tone = form.querySelector('[name="tone"]');
        if (tone && params.tone) tone.value = params.tone;
        var web = form.querySelector('[name="website_url"]');
        if (web && params.website_url) web.value = params.website_url;
        var vert = form.querySelector('[name="business_vertical"]');
        if (vert && params.business_vertical) vert.value = params.business_vertical;
    }

    function buildBusinessVerticalOptionsHtml() {
        return BUSINESS_VERTICAL_OPTIONS.map(function (opt) {
            return (
                '<option value="' +
                esc(opt.id) +
                '">' +
                esc(opt.label) +
                "</option>"
            );
        }).join("");
    }

    function buildWriteToneOptionsHtml() {
        return WRITE_TONE_OPTIONS.map(function (tone) {
            var sel = tone === "Chuyên nghiệp" ? " selected" : "";
            return '<option value="' + esc(tone) + '"' + sel + ">" + esc(tone) + "</option>";
        }).join("");
    }

    function buildWriteFormHtml() {
        return (
            '<label class="gcb-label">Từ khóa chính<input class="gcb-input" name="primary_keyword" required placeholder="vd: dịch vụ SEO" /></label>' +
            '<label class="gcb-label">Website / URL dịch vụ<input class="gcb-input" name="website_url" type="url" inputmode="url" placeholder="https://example.com (tùy chọn)" /></label>' +
            '<label class="gcb-label gcb-vertical-label">Ngành kinh doanh<select class="gcb-input" name="business_vertical">' +
            buildBusinessVerticalOptionsHtml() +
            "</select></label>" +
            '<p class="gcb-hint gcb-vertical-hint">Chọn ngành nếu từ khóa mơ hồ và không có URL.</p>' +
            '<label class="gcb-label">Số từ<div class="gcb-wc-field" data-gcb-wc-field>' +
            '<select class="gcb-input" name="word_count_mode" data-gcb-wc-select>' +
            '<option value="800">800 từ</option><option value="1000">1000 từ</option>' +
            '<option value="1500" selected>1500 từ</option><option value="2000">2000 từ</option>' +
            '<option value="custom">Tùy chỉnh</option></select>' +
            '<input class="gcb-input gcb-wc-custom-input" name="word_count" type="number" min="300" max="5000" step="1" inputmode="numeric" placeholder="Nhập số từ" hidden disabled data-gcb-wc-input />' +
            "</div></label>" +
            '<label class="gcb-label">Nguồn ảnh<select class="gcb-input" name="image_source">' +
            '<option value="none">Không chèn ảnh</option><option value="google" selected>Lấy ảnh Google</option>' +
            '<option value="ai">Tạo ảnh AI</option></select></label>' +
            '<span class="gcb-img-preview" hidden aria-hidden="true"></span>' +
            '<label class="gcb-label">Giọng văn<select class="gcb-input" name="tone">' +
            buildWriteToneOptionsHtml() +
            "</select></label>"
        );
    }

    function resolveWriteFormWordCount(form) {
        var parts = getWriteWordCountField(form);
        var wc = 1500;
        if (parts.select && parts.select.value === "custom") {
            wc = Number(parts.input && parts.input.value) || 0;
            wc = Math.max(WRITE_WORD_COUNT_MIN, Math.min(WRITE_WORD_COUNT_MAX, wc));
        } else if (parts.select) {
            wc = Number(parts.select.value) || 1500;
        }
        return wc;
    }

    function validateWriteWordCount(form) {
        var parts = getWriteWordCountField(form);
        if (!parts.select || parts.select.value !== "custom") return "";
        var raw = String((parts.input && parts.input.value) || "").trim();
        if (!raw) return "Vui lòng nhập số từ tùy chỉnh.";
        if (!/^\d+$/.test(raw)) return "Số từ chỉ được nhập số.";
        var n = Number(raw);
        if (n < WRITE_WORD_COUNT_MIN) {
            return "Số từ tối thiểu là " + WRITE_WORD_COUNT_MIN + ".";
        }
        if (n > WRITE_WORD_COUNT_MAX) {
            return "Số từ tối đa là " + WRITE_WORD_COUNT_MAX + ".";
        }
        return "";
    }

    function bindWriteFormHelpers(form) {
        var parts = getWriteWordCountField(form);
        var wcSelect = parts.select;
        var wcInput = parts.input;
        var imgPrev = form.querySelector(".gcb-img-preview");
        var imgSel = form.querySelector('[name="image_source"]');

        function upd() {
            if (!imgSel) return;
            var n = imageCountForWc(resolveWriteFormWordCount(form));
            var src = imgSel.value;
            if (imgPrev) {
                imgPrev.textContent =
                    src === "none"
                        ? "Không chèn ảnh."
                        : "Sẽ chèn " + n + " ảnh (" + (src === "ai" ? "AI" : "Google") + ").";
            }
        }

        applyWriteWordCountMode(form, false);

        if (wcSelect) {
            wcSelect.addEventListener("change", function () {
                if (wcSelect.value === "custom") applyWriteWordCountMode(form, true);
                else applyWriteWordCountMode(form, false);
                upd();
            });
        }
        if (wcInput) {
            wcInput.addEventListener("input", function () {
                var digits = wcInput.value.replace(/\D/g, "");
                if (wcInput.value !== digits) wcInput.value = digits;
                wcInput.classList.remove("gcb-input--invalid");
                upd();
            });
        }
        if (imgSel) imgSel.addEventListener("change", upd);
        upd();
    }

    function buildResearchFormHtml() {
        return (
            '<label class="gcb-label">Từ khóa gốc<input class="gcb-input" name="seed_keyword" required placeholder="vd: phần mềm CRM" /></label>' +
            '<label class="gcb-label">Quốc gia<select class="gcb-input" name="country">' +
            '<option value="VN" selected>Việt Nam</option><option value="US">United States</option><option value="SG">Singapore</option><option value="TH">Thailand</option>' +
            "</select></label>" +
            '<label class="gcb-label">Ngôn ngữ<select class="gcb-input" name="language">' +
            '<option value="vi" selected>Tiếng Việt</option><option value="en">English</option>' +
            "</select></label>" +
            '<label class="gcb-label">Số lượng keyword<select class="gcb-input" name="max_keywords">' +
            '<option value="50">50</option><option value="100" selected>100</option><option value="200">200</option><option value="500">500</option>' +
            "</select></label>"
        );
    }

    var CONTENT_AI_PREFILL_KEY = "seoauto_content_ai_prefill";

    function openContentAiWithPrefill(cluster) {
        if (!cluster || typeof cluster !== "object") return;
        var payload = {
            mode: "single",
            data: {
                primary_keyword: cluster.primary_keyword || "",
                secondary_keywords: cluster.secondary_keywords || [],
                recommended_title: cluster.suggested_title || "",
                meta_description: cluster.meta_description || "",
                custom_outline: cluster.suggested_outline || "",
                outline: cluster.suggested_outline || "",
                intent: cluster.intent || "",
                target_word_count: cluster.target_word_count || "",
            },
        };
        try {
            sessionStorage.setItem(CONTENT_AI_PREFILL_KEY, JSON.stringify(payload));
        } catch (_) {}
        var onContentAi = window.location && window.location.pathname && window.location.pathname.indexOf("/content-ai") >= 0;
        if (onContentAi) {
            window.dispatchEvent(new CustomEvent("digiseo:content-ai-prefill"));
            switchTab("write");
            return;
        }
        window.location.href = "/content-ai";
    }

    function renderFormFields(tabId, intent, container) {
        container.innerHTML = "";
        var form = document.createElement("form");
        form.className = "gcb-form";
        form.noValidate = !isWriteIntent(intent);

        if (isWriteIntent(intent)) {
            form.className = "gcb-form gcb-form--write";
            form.innerHTML = buildWriteFormHtml();
            bindWriteFormHelpers(form);
            var stForm = getWorkflowState(tabId);
            if (stForm && stForm.formParams) prefillWriteForm(form, stForm.formParams);
            var pkInput = form.querySelector('[name="primary_keyword"]');
            if (pkInput) {
                pkInput.addEventListener("input", function () {
                    pkInput.classList.remove("gcb-input--invalid");
                    clearWriteFormInvalid(form);
                });
            }
        } else if (intent === "url_seo_scoreboard") {
            form.innerHTML =
                '<label class="gcb-label">URL cần chấm điểm<input class="gcb-input" name="url" required placeholder="https://example.com/page" /></label>' +
                '<label class="gcb-label">Từ khóa chính<input class="gcb-input" name="primary_keyword" required placeholder="vd: dịch vụ thiết kế web" /></label>';
        } else if (intent === "content_seo_score") {
            form.innerHTML =
                '<label class="gcb-label">Từ khóa chính<input class="gcb-input" name="primary_keyword" required placeholder="vd: dịch vụ SEO" /></label>' +
                '<label class="gcb-label">Nội dung bài viết<textarea class="gcb-input gcb-textarea" name="content_html" rows="8" required placeholder="Dán HTML hoặc nội dung bài viết…"></textarea></label>' +
                '<p class="gcb-hint">Có thể dán HTML từ editor hoặc văn bản thuần.</p>';
        } else if (intent === "technical_quick_audit") {
            form.innerHTML =
                '<label class="gcb-label">URL website<input class="gcb-input" name="url" required placeholder="https://example.com" /></label>' +
                '<p class="gcb-hint">Crawl nhanh tối đa ~10 trang, kiểm tra lỗi technical cơ bản.</p>';
        } else if (intent === "technical_deep_audit") {
            form.innerHTML =
                '<label class="gcb-label">URL website<input class="gcb-input" name="url" required placeholder="https://example.com" /></label>' +
                '<label class="gcb-label">Số trang muốn crawl<input class="gcb-input" name="max_pages" type="number" min="5" max="200" value="50" /></label>' +
                '<p class="gcb-hint">Quét nhiều trang, phân tích chi tiết và lưu báo cáo vào tài khoản.</p>';
        } else if (intent === "technical_single_url") {
            form.innerHTML =
                '<label class="gcb-label">URL cần kiểm tra<input class="gcb-input" name="url" required placeholder="https://example.com/page" /></label>' +
                '<p class="gcb-hint">Kiểm tra technical cho đúng 1 URL (HTTP status, index, canonical, robots…).</p>';
        } else if (intent === "keyword_research" || intent === "keyword_research_cluster") {
            form.innerHTML = buildResearchFormHtml();
            if (intent === "keyword_research_cluster") {
                form.innerHTML += '<p class="gcb-hint">Sau khi chạy: bảng cụm từ khóa + nút «Viết bài SEO» để điền sẵn form Content AI.</p>';
            } else {
                form.innerHTML += '<p class="gcb-hint">Chỉ mở rộng từ khóa liên quan — không gom cụm, không viết bài.</p>';
            }
        }

        var actions = document.createElement(TAG_DIV);
        actions.className = "gcb-form-actions";
        var btnBack = document.createElement("button");
        btnBack.type = "button";
        btnBack.className = "gcb-btn gcb-btn--ghost";
        btnBack.textContent = "← Quay lại";
        btnBack.addEventListener("click", function () {
            var stLocal = getWorkflowState(tabId);
            stLocal.phase = "cards";
            stLocal.intent = null;
            stLocal.tabRevealed = true;
            renderTabPanel(tabId);
        });
        var btnEst = document.createElement("button");
        btnEst.type = "submit";
        btnEst.className = "gcb-btn gcb-btn--primary";
        btnEst.textContent = isWriteIntent(intent) ? "Tạo outline" : "Ước tính credit";
        actions.appendChild(btnBack);
        actions.appendChild(btnEst);
        form.appendChild(actions);

        form.addEventListener("submit", function (e) {
            e.preventDefault();
            var pkInput = form.querySelector('[name="primary_keyword"]');
            if (pkInput) pkInput.classList.remove("gcb-input--invalid");
            if (isWriteIntent(intent)) submitPreviewOutline(tabId, intent, form);
            else submitPrepare(tabId, intent, form);
        });
        container.appendChild(form);
    }

    function collectParams(form) {
        if (!form) return {};
        var params = {};
        form.querySelectorAll("input, select, textarea").forEach(function (el) {
            var name = el.name;
            if (!name || name === "word_count_mode") return;
            if (name === "word_count" && (el.hidden || el.disabled)) return;
            if (el.type === "checkbox") params[name] = el.checked;
            else if (el.type === "number") params[name] = Number(el.value) || 0;
            else params[name] = String(el.value || "").trim();
        });
        if (form.querySelector("[data-gcb-wc-select]")) {
            params.word_count = resolveWriteFormWordCount(form);
        }
        if (params.primary_keyword && !params.keyword) {
            params.keyword = params.primary_keyword;
        }
        if (!params.tone) params.tone = "Chuyên nghiệp";
        delete params.word_count_preset;
        delete params.word_count_custom;
        delete params.word_count_mode;
        return params;
    }

    function formatOutlineHtml(outline) {
        var raw = String(outline || "").trim();
        if (!raw) return "<p class=\"gcb-muted\">(Chưa có outline)</p>";
        if (raw.indexOf("<") >= 0) return raw;
        return "<pre class=\"gcb-outline-pre\">" + esc(raw) + "</pre>";
    }

    async function submitPreviewOutline(tabId, intent, form) {
        if (!getToken()) {
            showGuestNotice(true);
            return;
        }
        var st = getWorkflowState(tabId);
        if (st.loadingCardId) return;
        form = resolveFormElement(tabId, form);
        var params = mergeWriteParams(form, st);
        var validationMsg = validateWriteParams(params, form);
        if (validationMsg) {
            showFormValidationError(tabId, form, validationMsg);
            return;
        }
        clearWriteFormInvalid(form);
        st.formParams = params;
        st.intent = intent;
        st.returnPhase = "form";
        var cardId = showWorkflowLoading({
            tabId: tabId,
            message: intent === "keyword_cluster_to_article" ? "Đang research & tạo outline…" : "Đang tạo outline…",
            steps: presetSteps("preview_outline", "validate"),
        });
        try {
            updateWorkflowProgress({
                tabId: tabId,
                cardId: cardId,
                steps: presetSteps("preview_outline", "outline"),
            });
            var res = await apiFetch(
                ["/api/chatbot/workflows/preview-outline", "/chatbot/workflows/preview-outline"],
                {
                    method: "POST",
                    headers: authHeaders(),
                    body: JSON.stringify({ intent: intent, params: params }),
                }
            );
            var data = await res.json().catch(function () {
                return {};
            });
            if (!res.ok) throw new Error(parseApiErrorDetail(data) || "HTTP " + res.status);
            updateWorkflowProgress({
                tabId: tabId,
                cardId: cardId,
                steps: markAllStepsDone(presetSteps("preview_outline", "credit")),
            });
            hideWorkflowLoading({ tabId: tabId, cardId: cardId });
            st.phase = "outline";
            st.planning = data.planning;
            st.credits = data.credits;
            st.balance = data.balance;
            st.sufficient = data.sufficient;
            st.creditEstimateMessage = data.credit_estimate_message;
            st.insufficientMessage = data.insufficient_message;
            st.creditRequired = data.credit_required;
            st.creditBalance = data.credit_balance;
            st.prepare = null;
            st.workflowId = null;
            st.errorMessage = null;
            st.pendingRetry = null;
            renderTabPanel(tabId);
        } catch (err) {
            var errMsg = err.message || String(err);
            st.pendingRetry = function () {
                submitPreviewOutline(tabId, intent, resolveFormElement(tabId, null));
            };
            if (isAmbiguousKeywordError(errMsg)) {
                hideWorkflowLoading({ tabId: tabId, cardId: cardId });
                st.phase = "form";
                st.returnPhase = "form";
                renderTabPanel(tabId);
                var formEl = resolveFormElement(tabId, null);
                highlightAmbiguousWriteForm(formEl);
                showFormValidationError(
                    tabId,
                    formEl,
                    errMsg.replace(/^AMBIGUOUS_KEYWORD:\s*/i, "").trim()
                );
                return;
            }
            showWorkflowError({
                tabId: tabId,
                cardId: cardId,
                message: errMsg,
            });
        }
    }

    async function submitPrepare(tabId, intent, form) {
        if (!getToken()) {
            showGuestNotice(true);
            return;
        }
        var st = getWorkflowState(tabId);
        var params = collectParams(form);
        st.formParams = params;
        st.intent = intent;
        st.returnPhase = "form";
        var cardId = showWorkflowLoading({
            tabId: tabId,
            message: "Đang ước tính credit…",
            steps: presetSteps("prepare", "validate"),
        });
        try {
            updateWorkflowProgress({
                tabId: tabId,
                cardId: cardId,
                steps: presetSteps("prepare", "credit"),
            });
            var res = await apiFetch(["/api/chatbot/workflows/prepare", "/chatbot/workflows/prepare"], {
                method: "POST",
                headers: authHeaders(),
                body: JSON.stringify({
                    intent: intent,
                    params: params,
                    session_id: getSessionId(),
                }),
            });
            var data = await res.json().catch(function () {
                return {};
            });
            if (!res.ok) throw new Error(parseApiErrorDetail(data) || "HTTP " + res.status);
            hideWorkflowLoading({ tabId: tabId, cardId: cardId });
            st.phase = "confirm";
            st.workflowId = data.workflow_id;
            st.credits = data.credits;
            st.prepare = data;
            st.creditEstimateMessage = data.credit_estimate_message;
            st.insufficientMessage = data.insufficient_message;
            st.errorMessage = null;
            st.pendingRetry = null;
            renderTabPanel(tabId);
        } catch (err) {
            st.pendingRetry = function () {
                var f = document.querySelector('[data-gcb-panel="' + tabId + '"] .gcb-form');
                submitPrepare(tabId, intent, f);
            };
            showWorkflowError({
                tabId: tabId,
                cardId: cardId,
                message: err.message || String(err),
            });
        }
    }

    async function confirmWriteAndStart(tabId) {
        var st = getWorkflowState(tabId);
        if (!st.intent || !st.planning || !st.formParams) return;
        st.returnPhase = "outline";
        var cardId = showWorkflowLoading({
            tabId: tabId,
            message: "Đang khởi chạy viết bài…",
            steps: presetSteps("confirm_start", "confirm"),
        });
        try {
            updateWorkflowProgress({
                tabId: tabId,
                cardId: cardId,
                steps: presetSteps("confirm_start", "start"),
            });
            var res = await apiFetch(["/api/chatbot/workflows/prepare", "/chatbot/workflows/prepare"], {
                method: "POST",
                headers: authHeaders(),
                body: JSON.stringify({
                    intent: st.intent,
                    params: st.formParams,
                    planning_snapshot: st.planning,
                    session_id: getSessionId(),
                }),
            });
            var data = await res.json().catch(function () {
                return {};
            });
            if (!res.ok) throw new Error(parseApiErrorDetail(data) || "HTTP " + res.status);
            st.workflowId = data.workflow_id;
            st.prepare = data;
            st.credits = data.credits;
            if (!data.sufficient) {
                hideWorkflowLoading({ tabId: tabId, cardId: cardId });
                st.pendingRetry = function () {
                    confirmWriteAndStart(tabId);
                };
                showWorkflowError({
                    tabId: tabId,
                    message: insufficientCreditText(data),
                });
                return;
            }
            var sres = await apiFetch(["/api/chatbot/workflows/start", "/chatbot/workflows/start"], {
                method: "POST",
                headers: authHeaders(),
                body: JSON.stringify({ workflow_id: st.workflowId }),
            });
            var sdata = await sres.json().catch(function () {
                return {};
            });
            if (!sres.ok) {
                var msg = parseApiErrorDetail(sdata) || "HTTP " + sres.status;
                if (sres.status === 402) msg = insufficientCreditText(sdata.detail || sdata);
                throw new Error(msg);
            }
            st.phase = "running";
            st.progress = sdata.progress || [];
            st.returnPhase = "outline";
            hideWorkflowLoading({ tabId: tabId, cardId: cardId });
            renderTabPanel(tabId);
            pollWorkflow(tabId, st.workflowId);
        } catch (err) {
            st.pendingRetry = function () {
                confirmWriteAndStart(tabId);
            };
            showWorkflowError({
                tabId: tabId,
                cardId: cardId,
                message: err.message || String(err),
            });
        }
    }

    function parseApiErrorDetail(data) {
        var d = data && data.detail;
        if (typeof d === "string") return d;
        if (d && typeof d === "object" && d.message) return String(d.message);
        return (data && data.message) || "";
    }

    function resolveFormElement(tabId, form) {
        if (form && form.querySelector) return form;
        var panel = document.querySelector('[data-gcb-panel="' + tabId + '"]');
        if (!panel) return null;
        return panel.querySelector(".gcb-form");
    }

    function mergeWriteParams(form, st) {
        var fromForm = form ? collectParams(form) : {};
        var saved = (st && st.formParams) || {};
        var params = Object.assign({}, saved, fromForm);
        var keyword = String(
            fromForm.primary_keyword ||
                fromForm.keyword ||
                saved.primary_keyword ||
                saved.keyword ||
                ""
        ).trim();
        if (keyword.length >= 2) {
            params.primary_keyword = keyword;
            params.keyword = keyword;
        }
        if (form && form.querySelector("[data-gcb-wc-select]")) {
            params.word_count = resolveWriteFormWordCount(form);
        } else if (!params.word_count && saved.word_count) {
            params.word_count = saved.word_count;
        }
        if (!params.tone) params.tone = saved.tone || "Chuyên nghiệp";
        if (!params.image_source) params.image_source = saved.image_source || "google";
        var web = String(params.website_url || saved.website_url || "").trim();
        if (web) {
            params.website_url = web;
            params.target_website = web;
        }
        var vertical = String(params.business_vertical || saved.business_vertical || "").trim();
        if (vertical) params.business_vertical = vertical;
        return params;
    }

    function isAmbiguousKeywordError(message) {
        return String(message || "").indexOf("AMBIGUOUS_KEYWORD") >= 0;
    }

    function highlightAmbiguousWriteForm(form) {
        if (!form) return;
        form.classList.add("gcb-form--need-vertical");
        var web = form.querySelector('[name="website_url"]');
        var vert = form.querySelector('[name="business_vertical"]');
        if (web) {
            web.classList.add("gcb-input--invalid");
            try {
                web.focus();
            } catch (_) {}
        }
        if (vert && vert.closest(".gcb-vertical-label")) {
            vert.closest(".gcb-vertical-label").classList.add("gcb-label--highlight");
        }
    }

    function validateWriteParams(params, form) {
        var keyword = String(params.primary_keyword || params.keyword || "").trim();
        if (keyword.length < 2) {
            return "Vui lòng nhập từ khóa chính (ít nhất 2 ký tự).";
        }
        if (form) {
            var wcMsg = validateWriteWordCount(form);
            if (wcMsg) return wcMsg;
        }
        return "";
    }

    function showFormValidationError(tabId, form, message) {
        if (form) {
            var pk = form.querySelector('[name="primary_keyword"]');
            if (pk && message.indexOf("từ khóa") >= 0) {
                pk.classList.add("gcb-input--invalid");
                pk.focus();
                try {
                    pk.scrollIntoView({ block: "center", behavior: "smooth" });
                } catch (_) {}
            }
            var wcInput = form.querySelector("[data-gcb-wc-input]");
            if (wcInput && message.indexOf("Số từ") >= 0) {
                wcInput.classList.add("gcb-input--invalid");
                applyWriteWordCountMode(form, true, wcInput.value || "");
                try {
                    wcInput.focus();
                    wcInput.scrollIntoView({ block: "center", behavior: "smooth" });
                } catch (_) {}
            }
        }
        var stage = ensureStageSection(tabId);
        if (stage) {
            stage.hidden = false;
            stage.innerHTML =
                '<div class="gcb-wf-card gcb-wf-card--error" role="alert">' +
                '<p class="gcb-wf-error-msg">' +
                esc(message) +
                "</p></div>";
        }
    }

    function clearWriteFormInvalid(form) {
        if (!form) return;
        var pk = form.querySelector('[name="primary_keyword"]');
        if (pk) pk.classList.remove("gcb-input--invalid");
        var panel = form.closest("[data-gcb-panel]");
        if (panel) {
            var stage = panel.querySelector('[data-gcb-section="stage"]');
            if (stage && !stage.querySelector("[data-gcb-wf-retry]")) {
                stage.hidden = true;
                stage.innerHTML = "";
            }
        }
    }

    function creditEstimateText(data) {
        if (data && data.credit_estimate_message) return data.credit_estimate_message;
        var total =
            (data && data.credit_required) ||
            (data && data.credits && data.credits.total) ||
            0;
        return "Tác vụ này dự kiến tốn " + total + " credit.";
    }

    function insufficientCreditText(data) {
        if (data && data.insufficient_message) return data.insufficient_message;
        var req =
            (data && data.credit_required) ||
            (data && data.credits && data.credits.total) ||
            0;
        var bal =
            (data && data.credit_balance) != null
                ? data.credit_balance
                : data && data.balance != null
                  ? data.balance
                  : null;
        if (bal != null) {
            return "Bạn cần " + req + " credit, tài khoản hiện có " + bal + " credit.";
        }
        return "Bạn cần " + req + " credit.";
    }

    function renderCreditLines(credits) {
        var lines = [];
        var map = [
            ["Viết bài", credits.content_ai],
            ["Research", credits.research],
            ["Gom nhóm", credits.clustering],
            ["Internal link", credits.internal_links],
            ["Ảnh Google", credits.images_google],
            ["Ảnh AI", credits.images_ai],
            ["SEO Score", credits.seo_score],
            ["Technical", credits.technical],
        ];
        map.forEach(function (row) {
            if (Number(row[1]) > 0) lines.push("<li>" + esc(row[0]) + ": <strong>" + row[1] + "</strong> credit</li>");
        });
        return lines.join("");
    }

    function renderOutlinePanel(tabId, container) {
        var st = getWorkflowState(tabId);
        var plan = st.planning || {};
        var credits = st.credits || {};
        var secondary = (plan.secondary_keywords || []).join(", ");
        var deepMeta =
            plan.mode === "deep" && plan.keywords_found
                ? "<p class=\"gcb-hint\">Research: " +
                  esc(String(plan.keywords_found)) +
                  " từ khóa · " +
                  esc(String(plan.clusters_found || 0)) +
                  " cụm</p>"
                : "";
        var wctx = plan.website_context || {};
        var websiteMeta = "";
        if (plan.website_url || wctx.url || wctx.industry_label) {
            websiteMeta =
                '<div class="gcb-outline-block gcb-outline-block--website">' +
                '<span class="gcb-outline-label">Ngữ cảnh website</span>' +
                '<p class="gcb-outline-value">' +
                (plan.website_url || wctx.url
                    ? "<strong>URL:</strong> " + esc(String(plan.website_url || wctx.url)) + "<br>"
                    : "") +
                (wctx.industry_label ? "<strong>Ngành:</strong> " + esc(String(wctx.industry_label)) + "<br>" : "") +
                (wctx.services ? "<strong>Dịch vụ:</strong> " + esc(String(wctx.services)) + "<br>" : "") +
                (wctx.region ? "<strong>Khu vực:</strong> " + esc(String(wctx.region)) : "") +
                "</p></div>";
        }

        container.innerHTML =
            '<div class="gcb-outline">' +
            '<p class="gcb-confirm-title">Preview outline</p>' +
            deepMeta +
            websiteMeta +
            '<div class="gcb-outline-block"><span class="gcb-outline-label">Tiêu đề</span><p class="gcb-outline-value">' +
            esc(String(plan.title || "")) +
            "</p></div>" +
            '<div class="gcb-outline-block"><span class="gcb-outline-label">Meta description</span><p class="gcb-outline-value">' +
            esc(String(plan.meta_description || "")) +
            "</p></div>" +
            (secondary
                ? '<div class="gcb-outline-block"><span class="gcb-outline-label">Từ khóa phụ</span><p class="gcb-outline-value">' +
                  esc(secondary) +
                  "</p></div>"
                : "") +
            '<div class="gcb-outline-block"><span class="gcb-outline-label">Dàn ý H2/H3</span><div class="gcb-outline-body">' +
            formatOutlineHtml(plan.outline) +
            "</div></div>" +
            '<p class="gcb-credit-estimate">' + esc(creditEstimateText(st)) + "</p>" +
            '<ul class="gcb-credits">' +
            renderCreditLines(credits) +
            "</ul>" +
            '<p class="gcb-credits-total">Tổng: <strong>' +
            esc(String(credits.total || 0)) +
            "</strong> credit" +
            (st.balance != null ? " · Số dư: <strong>" + esc(String(st.balance)) + "</strong>" : "") +
            "</p>" +
            (!st.sufficient && st.balance != null
                ? '<p class="gcb-error">' + esc(insufficientCreditText(st)) + "</p>"
                : "") +
            '<div class="gcb-form-actions">' +
            '<button type="button" class="gcb-btn gcb-btn--ghost" data-gcb-outline-back>← Sửa form</button>' +
            '<button type="button" class="gcb-btn gcb-btn--primary" data-gcb-write-confirm ' +
            (st.sufficient === false ? "disabled" : "") +
            ">Xác nhận & viết bài</button>" +
            "</div></div>";

        container.querySelector("[data-gcb-outline-back]").addEventListener("click", function () {
            st.phase = "form";
            renderTabPanel(tabId);
        });
        container.querySelector("[data-gcb-write-confirm]").addEventListener("click", function () {
            confirmWriteAndStart(tabId);
        });
    }

    function renderProgressList(container, progress) {
        container.innerHTML = "";
        var ul = document.createElement("ul");
        ul.className = "gcb-progress";
        (progress || []).forEach(function (step) {
            var li = document.createElement("li");
            var st = String(step.status || "pending");
            li.className = "gcb-progress-item gcb-progress-item--" + st;
            li.innerHTML =
                '<span class="gcb-progress-dot"></span><span class="gcb-progress-label">' +
                esc(String(step.label || step.id || "")) +
                "</span>";
            ul.appendChild(li);
        });
        container.appendChild(ul);
    }

    function openArticleInEditor(articleId) {
        if (!articleId) return;
        var pid = String(articleId).trim();
        var path = window.location && window.location.pathname ? window.location.pathname : "";
        var onContentAi = path.indexOf("/content-ai") >= 0;
        if (onContentAi && typeof window.DigiSeoLoadContentAiProject === "function") {
            void window.DigiSeoLoadContentAiProject(pid);
            return;
        }
        window.location.href = "/content-ai?article_id=" + encodeURIComponent(pid);
    }

    function renderMetricRow(label, value) {
        return (
            '<div class="gcb-seo-metric"><span class="gcb-seo-metric-label">' +
            esc(label) +
            '</span><span class="gcb-seo-metric-value">' +
            esc(String(value || "—")) +
            "</span></div>"
        );
    }

    function renderHeadingList(headings) {
        var h = headings || {};
        var parts = [];
        ["h1", "h2", "h3"].forEach(function (tag) {
            var list = h[tag] || [];
            if (list.length) parts.push(tag.toUpperCase() + ": " + list.slice(0, 4).join(" · "));
        });
        return parts.length ? parts.join("\n") : "—";
    }

    function renderIssueGroup(title, cls, items) {
        if (!items || !items.length) return "";
        var lis = items
            .map(function (it) {
                return (
                    "<li><strong>" +
                    esc(it.title || "") +
                    "</strong>" +
                    (it.message ? "<span>" + esc(it.message) + "</span>" : "") +
                    (it.suggestion ? '<em class="gcb-seo-fix">' + esc(it.suggestion) + "</em>" : "") +
                    "</li>"
                );
            })
            .join("");
        return (
            '<div class="gcb-seo-issues gcb-seo-issues--' +
            cls +
            '"><h4>' +
            esc(title) +
            " (" +
            items.length +
            ')</h4><ul>' +
            lis +
            "</ul></div>"
        );
    }

    function renderSeoScoreResult(container, report) {
        container.innerHTML = "";
        var box = document.createElement(TAG_DIV);
        box.className = "gcb-result gcb-seo-result";
        var score = Number(report.total_score || 0);
        var passed = !!report.passed;
        var ringColor = score >= 75 ? "#22c55e" : score >= 60 ? "#f59e0b" : "#ef4444";
        var metrics = report.metrics || {};
        var density = metrics.keyword_density || {};
        var issues = report.issues || {};

        box.innerHTML =
            '<div class="gcb-seo-head">' +
            '<div class="gcb-seo-ring" style="--gcb-ring-pct:' +
            score +
            ";--gcb-ring-color:" +
            ringColor +
            '"><span class="gcb-seo-ring-val">' +
            score +
            '</span><span class="gcb-seo-ring-sub">/100</span></div>' +
            '<div class="gcb-seo-head-meta">' +
            '<p class="gcb-seo-grade">' +
            esc(String(report.grade_label || "")) +
            '</p><p class="gcb-seo-pass ' +
            (passed ? "is-pass" : "is-fail") +
            '">' +
            (passed ? "Đạt" : "Chưa đạt") +
            "</p>" +
            (report.url ? '<p class="gcb-hint">' + esc(report.url) + "</p>" : "") +
            (report.primary_keyword ? '<p class="gcb-hint">Từ khóa: <strong>' + esc(report.primary_keyword) + "</strong></p>" : "") +
            "</div></div>";

        if ((report.group_scores || []).length) {
            var bars = (report.group_scores || [])
                .map(function (g) {
                    var s = Number(g.score || 0);
                    return (
                        '<div class="gcb-seo-bar-row"><span class="gcb-seo-bar-label">' +
                        esc(String(g.label || g.id || "")) +
                        '</span><div class="gcb-seo-bar"><span style="width:' +
                        Math.max(0, Math.min(100, s)) +
                        '%"></span></div><span class="gcb-seo-bar-num">' +
                        s +
                        "</span></div>"
                    );
                })
                .join("");
            box.innerHTML += '<div class="gcb-seo-bars">' + bars + "</div>";
        }

        box.innerHTML +=
            '<div class="gcb-seo-metrics">' +
            renderMetricRow("Title", metrics.title) +
            renderMetricRow("Meta description", metrics.meta_description) +
            renderMetricRow("H1 / H2 / H3", renderHeadingList(metrics.headings)) +
            renderMetricRow(
                "Mật độ từ khóa",
                density.density_pct != null
                    ? density.density_pct + "% (" + (density.count || 0) + " lần / " + (density.word_count || 0) + " từ)"
                    : "—"
            ) +
            renderMetricRow("Từ khóa phụ", metrics.secondary_keywords) +
            renderMetricRow("Search intent", metrics.search_intent) +
            renderMetricRow(
                "Internal link",
                (metrics.internal_links && metrics.internal_links.count != null ? metrics.internal_links.count + " link · " : "") +
                    (metrics.internal_links && metrics.internal_links.message ? metrics.internal_links.message : metrics.internal_links && metrics.internal_links.status_label ? metrics.internal_links.status_label : "")
            ) +
            renderMetricRow(
                "External link",
                (metrics.external_links && metrics.external_links.count != null ? metrics.external_links.count + " link · " : "") +
                    (metrics.external_links && metrics.external_links.message ? metrics.external_links.message : metrics.external_links && metrics.external_links.status_label ? metrics.external_links.status_label : "")
            ) +
            renderMetricRow(
                "Hình ảnh / ALT",
                (metrics.images && metrics.images.total != null ? metrics.images.total + " ảnh" : "") +
                    (metrics.images && metrics.images.missing_alt ? ", thiếu alt: " + metrics.images.missing_alt : "") +
                    (metrics.images && metrics.images.status_label ? " · " + metrics.images.status_label : "")
            ) +
            renderMetricRow("Readability", (metrics.readability && (metrics.readability.status_label || metrics.readability.message)) || "—") +
            renderMetricRow("FAQ", (metrics.faq && (metrics.faq.status_label || metrics.faq.message)) || "—") +
            renderMetricRow("Schema", (metrics.schema && (metrics.schema.message || (metrics.schema.has_schema ? "Có schema" : "Chưa có schema"))) || "—") +
            renderMetricRow("CTA / Kết luận", (metrics.cta && (metrics.cta.status_label || metrics.cta.message)) || "—") +
            renderMetricRow("E-E-A-T", (metrics.eeat && (metrics.eeat.status_label || metrics.eeat.message)) || "—") +
            "</div>";

        var issuesHtml =
            renderIssueGroup("Nghiêm trọng", "critical", issues.critical) +
            renderIssueGroup("Cảnh báo", "warning", issues.warning) +
            renderIssueGroup("Gợi ý tối ưu", "suggestion", issues.suggestion);
        if (issuesHtml) {
            box.innerHTML += '<div class="gcb-seo-issues-wrap">' + issuesHtml + "</div>";
        }

        var btn = document.createElement("button");
        btn.type = "button";
        btn.className = "gcb-btn gcb-btn--ghost";
        btn.textContent = "Chấm điểm mới";
        btn.addEventListener("click", function () {
            workflowState[activeTab] = resetWorkflowState();
            renderTabPanel(activeTab);
        });
        box.appendChild(btn);
        container.appendChild(box);
    }

    function renderHeadingTechList(headings) {
        if (!headings || typeof headings !== "object") return "—";
        var parts = [];
        ["h1", "h2", "h3"].forEach(function (tag) {
            var arr = headings[tag] || [];
            if (arr.length) parts.push(tag.toUpperCase() + ": " + arr.slice(0, 3).join(" · "));
        });
        return parts.length ? parts.join(" | ") : "—";
    }

    function renderTechnicalResult(container, report) {
        container.innerHTML = "";
        var box = document.createElement(TAG_DIV);
        box.className = "gcb-result gcb-seo-result gcb-tech-result";
        var score = Number(report.health_score || 0);
        var ringColor = score >= 75 ? "#22c55e" : score >= 60 ? "#f59e0b" : "#ef4444";
        var ov = report.overview || {};
        var issues = report.issues || {};
        var modeLabel = { quick: "Audit nhanh", deep: "Audit chuyên sâu", single: "Kiểm tra URL" }[report.mode] || "Technical";

        box.innerHTML =
            '<div class="gcb-seo-head">' +
            '<div class="gcb-seo-ring" style="--gcb-ring-pct:' +
            score +
            ";--gcb-ring-color:" +
            ringColor +
            '"><span class="gcb-seo-ring-val">' +
            score +
            '</span><span class="gcb-seo-ring-sub">/100</span></div>' +
            '<div class="gcb-seo-head-meta">' +
            '<p class="gcb-seo-grade">' +
            esc(String(report.grade_label || "")) +
            '</p><p class="gcb-hint">' +
            esc(modeLabel) +
            (report.pages_scanned ? " · " + report.pages_scanned + " trang" : "") +
            "</p>" +
            (report.url ? '<p class="gcb-hint">' + esc(report.url) + "</p>" : "") +
            "</div></div>";

        box.innerHTML +=
            '<div class="gcb-seo-metrics gcb-tech-overview">' +
            '<h4 class="gcb-tech-section-title">Tổng quan</h4>' +
            renderMetricRow("HTTP status", ov.http_status) +
            renderMetricRow("Indexability", ov.indexability) +
            renderMetricRow("Canonical", ov.canonical) +
            renderMetricRow("Robots meta", ov.robots_meta) +
            renderMetricRow("Sitemap", ov.sitemap) +
            renderMetricRow("Title", ov.title) +
            renderMetricRow("Meta description", ov.meta_description) +
            renderMetricRow("Heading", renderHeadingTechList(ov.headings)) +
            renderMetricRow("Broken link", ov.broken_links != null ? String(ov.broken_links) : "—") +
            renderMetricRow("Redirect", ov.redirects != null ? String(ov.redirects) : "—") +
            renderMetricRow("Ảnh thiếu alt", ov.images_missing_alt != null ? String(ov.images_missing_alt) : "—") +
            renderMetricRow("Tốc độ", ov.page_speed || "—") +
            "</div>";

        var issuesHtml =
            renderIssueGroup("Lỗi nghiêm trọng", "critical", issues.critical) +
            renderIssueGroup("Cảnh báo", "warning", issues.warning) +
            renderIssueGroup("Gợi ý sửa", "suggestion", issues.suggestion);
        if (issuesHtml) {
            box.innerHTML += '<div class="gcb-seo-issues-wrap">' + issuesHtml + "</div>";
        }

        var btn = document.createElement("button");
        btn.type = "button";
        btn.className = "gcb-btn gcb-btn--ghost";
        btn.textContent = "Kiểm tra mới";
        btn.addEventListener("click", function () {
            workflowState[activeTab] = resetWorkflowState();
            renderTabPanel(activeTab);
        });
        box.appendChild(btn);
        container.appendChild(box);
    }

    function renderResearchResult(container, report) {
        container.innerHTML = "";
        var box = document.createElement(TAG_DIV);
        box.className = "gcb-result gcb-research-result";
        var mode = String(report.mode || "keywords");
        var seed = String(report.seed_keyword || "");
        var head = document.createElement("p");
        head.className = "gcb-hint";
        head.textContent =
            "Từ khóa gốc: " +
            seed +
            " · " +
            (report.total_keywords || 0) +
            " keyword" +
            (mode === "clusters" ? " · " + (report.total_clusters || 0) + " cụm" : "");
        box.appendChild(head);

        if (mode === "keywords" || (report.keywords && report.keywords.length)) {
            var kwTitle = document.createElement("h4");
            kwTitle.className = "gcb-tech-section-title";
            kwTitle.textContent = "Bảng từ khóa";
            box.appendChild(kwTitle);
            var kwWrap = document.createElement(TAG_DIV);
            kwWrap.className = "gcb-research-table-wrap";
            var kwRows = report.keywords || [];
            var kwHtml =
                '<table class="gcb-research-table"><thead><tr>' +
                "<th>Từ khóa</th><th>Volume</th><th>Intent</th><th>Độ khó</th><th>Competition</th><th>Xu hướng</th><th>CPC</th>" +
                "</tr></thead><tbody>";
            kwRows.forEach(function (row) {
                kwHtml +=
                    "<tr><td>" +
                    esc(row.keyword || "") +
                    "</td><td>" +
                    esc(row.volume != null ? String(row.volume) : "—") +
                    "</td><td>" +
                    esc(row.intent || "—") +
                    "</td><td>" +
                    esc(row.difficulty || "—") +
                    "</td><td>" +
                    esc(row.competition || "—") +
                    "</td><td>" +
                    esc(row.trend || "—") +
                    "</td><td>" +
                    esc(row.cpc || "—") +
                    "</td></tr>";
            });
            kwHtml += "</tbody></table>";
            kwWrap.innerHTML = kwHtml;
            box.appendChild(kwWrap);
        }

        if (mode === "clusters" && report.clusters && report.clusters.length) {
            var clTitle = document.createElement("h4");
            clTitle.className = "gcb-tech-section-title";
            clTitle.textContent = "Bảng cụm từ khóa";
            box.appendChild(clTitle);
            var clWrap = document.createElement(TAG_DIV);
            clWrap.className = "gcb-research-table-wrap";
            var clHtml =
                '<table class="gcb-research-table gcb-research-table--clusters"><thead><tr>' +
                "<th>Cụm</th><th>Từ khóa chính</th><th>Từ khóa phụ</th><th>Intent</th><th>Volume</th><th>Độ khó TB</th><th>Title gợi ý</th><th></th>" +
                "</tr></thead><tbody>";
            report.clusters.forEach(function (c, idx) {
                clHtml +=
                    "<tr><td>" +
                    esc(c.cluster_name || "") +
                    "</td><td>" +
                    esc(c.primary_keyword || "") +
                    "</td><td>" +
                    esc(c.secondary_keywords_text || "") +
                    "</td><td>" +
                    esc(c.intent || "—") +
                    "</td><td>" +
                    esc(c.total_volume != null ? String(c.total_volume) : "0") +
                    "</td><td>" +
                    esc(c.avg_difficulty || "—") +
                    "</td><td>" +
                    esc(c.suggested_title || "—") +
                    '</td><td><button type="button" class="gcb-btn gcb-btn--primary gcb-btn--sm" data-cluster-idx="' +
                    idx +
                    '">Viết bài SEO</button></td></tr>';
            });
            clHtml += "</tbody></table>";
            clWrap.innerHTML = clHtml;
            clWrap.querySelectorAll("[data-cluster-idx]").forEach(function (btn) {
                btn.addEventListener("click", function () {
                    var i = parseInt(btn.getAttribute("data-cluster-idx"), 10);
                    var cluster = report.clusters[i];
                    if (cluster) openContentAiWithPrefill(cluster);
                });
            });
            box.appendChild(clWrap);
        }

        var btn = document.createElement("button");
        btn.type = "button";
        btn.className = "gcb-btn gcb-btn--ghost";
        btn.textContent = "Research mới";
        btn.addEventListener("click", function () {
            workflowState[activeTab] = resetWorkflowState();
            renderTabPanel(activeTab);
        });
        box.appendChild(btn);
        container.appendChild(box);
    }

    function renderResult(container, data) {
        container.innerHTML = "";
        var run = (data && data.run) || {};
        var seoReport = data.seo_report || (run.result && run.result.seo_report) || null;
        if (seoReport) {
            renderSeoScoreResult(container, seoReport);
            return;
        }
        var techReport = data.technical_report || (run.result && run.result.technical_report) || null;
        if (techReport) {
            renderTechnicalResult(container, techReport);
            return;
        }
        var researchReport = data.research_report || (run.result && run.result.research_report) || null;
        if (researchReport) {
            renderResearchResult(container, researchReport);
            return;
        }

        var box = document.createElement(TAG_DIV);
        box.className = "gcb-result";
        var articleId = data.load_editor_article_id || data.article_id || "";
        run = (data && data.run) || {};
        if (!articleId && run.article) {
            articleId = run.article.article_id || run.article.project_id || "";
        }

        if (articleId) {
            var ok = document.createElement("p");
            ok.className = "gcb-result-text";
            ok.textContent = "Bài viết đã sẵn sàng trong editor Content AI.";
            box.appendChild(ok);
            openArticleInEditor(articleId);
        } else {
            var reply = String((data && data.reply) || "").trim();
            if (reply) {
                var p = document.createElement("div");
                p.className = "gcb-result-text";
                p.innerHTML = esc(reply).replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>").replace(/\n/g, "<br>");
                box.appendChild(p);
            }
        }

        var art = run.article || {};
        var seoSummary = art.seo_summary || (run.stats && run.stats.seo_summary) || null;
        if (seoSummary) {
            var seoBox = document.createElement("div");
            seoBox.className = "gcb-result-seo";
            var seoLines = [
                "Số từ yêu cầu: " + (seoSummary.requested_word_count != null ? seoSummary.requested_word_count : "—"),
                "Số từ thực tế: " + (seoSummary.actual_word_count != null ? seoSummary.actual_word_count : "—"),
                "SEO Score: " + (seoSummary.seo_score != null ? seoSummary.seo_score : "—") + "/100",
                "Yếu tố đạt: " + (seoSummary.passed_factors != null ? seoSummary.passed_factors : "—") + "/" + (seoSummary.total_factors || 30),
            ];
            if (seoSummary.failed_factor_labels && seoSummary.failed_factor_labels.length) {
                seoLines.push("Chưa đạt: " + seoSummary.failed_factor_labels.slice(0, 5).join(", "));
            } else if (seoSummary.warning_factor_labels && seoSummary.warning_factor_labels.length) {
                seoLines.push("Cần tối ưu thêm: " + seoSummary.warning_factor_labels.slice(0, 5).join(", "));
            }
            seoBox.innerHTML = seoLines.map(function (line) {
                return "<p class=\"gcb-result-seo-line\">" + esc(line) + "</p>";
            }).join("");
            box.appendChild(seoBox);
        } else if (art.seo_score != null || (run.stats && run.stats.seo_score != null)) {
            var scoreOnly = document.createElement("p");
            scoreOnly.className = "gcb-result-score";
            var sc = art.seo_score != null ? art.seo_score : run.stats.seo_score;
            var passed = art.passed_factors != null ? art.passed_factors : run.stats.passed_factors;
            var total = art.total_factors != null ? art.total_factors : (run.stats.total_factors || 30);
            scoreOnly.textContent = "SEO Score: " + sc + "/100 — " + passed + "/" + total + " yếu tố đạt";
            box.appendChild(scoreOnly);
        }

        var stats = run.stats || data.stats || {};
        if (stats.score != null && !seoSummary && art.seo_score == null) {
            var score = document.createElement("p");
            score.className = "gcb-result-score";
            score.textContent = "Điểm: " + stats.score + "/100";
            box.appendChild(score);
        }

        var actions = data.actions || run.actions || [];
        actions.forEach(function (act) {
            if (act.type === "open_url" && act.url && !articleId) {
                var a = document.createElement("a");
                a.className = "gcb-result-link";
                a.href = act.url;
                a.textContent = act.label || "Mở chi tiết";
                box.appendChild(a);
            }
        });

        var btn = document.createElement("button");
        btn.type = "button";
        btn.className = "gcb-btn gcb-btn--ghost";
        btn.textContent = "Chạy workflow mới";
        btn.addEventListener("click", function () {
            workflowState[activeTab] = resetWorkflowState();
            renderTabPanel(activeTab);
        });
        box.appendChild(btn);
        container.appendChild(box);
    }

    function stopPoll() {
        if (activePoll) {
            clearInterval(activePoll);
            activePoll = null;
        }
    }

    function pollWorkflow(tabId, workflowId) {
        stopPoll();
        var ticks = 0;
        activePoll = setInterval(async function () {
            ticks += 1;
            if (ticks > 600) {
                stopPoll();
                var stTimeout = getWorkflowState(tabId);
                if (stTimeout) {
                    stTimeout.pendingRetry = function () {
                        startWorkflow(tabId);
                    };
                    showWorkflowError({
                        tabId: tabId,
                        message: "Workflow quá thời gian chờ. Vui lòng thử lại.",
                    });
                }
                return;
            }
            try {
                var res = await apiFetch(
                    ["/api/chatbot/workflows/" + encodeURIComponent(workflowId) + "/status"],
                    { headers: authHeaders({}) }
                );
                if (!res.ok) return;
                var st = await res.json();
                var stLocal = getWorkflowState(tabId);
                stLocal.progress = st.progress;
                updateWorkflowProgress({
                    tabId: tabId,
                    message: getRunningMessage(tabId, stLocal),
                    steps: st.progress,
                });

                if (st.phase === "completed" || st.phase === "failed") {
                    stopPoll();
                    var rres = await apiFetch(
                        ["/api/chatbot/workflows/" + encodeURIComponent(workflowId) + "/result"],
                        { headers: authHeaders({}) }
                    );
                    var rdata = await rres.json().catch(function () {
                        return {};
                    });
                    if (st.phase === "failed" || rdata.error) {
                        stLocal.returnPhase = "form";
                        stLocal.pendingRetry = function () {
                            startWorkflow(tabId);
                        };
                        showWorkflowError({
                            tabId: tabId,
                            message: rdata.error || st.error || "Workflow thất bại.",
                        });
                        return;
                    }
                    showWorkflowResult(tabId, function () {
                        stLocal.phase = "result";
                        stLocal.result = rdata;
                        renderTabPanel(tabId);
                    });
                }
            } catch (_) {}
        }, 2000);
    }

    async function startWorkflow(tabId) {
        var st = getWorkflowState(tabId);
        if (!st.workflowId) return;
        st.returnPhase = "confirm";
        var cardId = showWorkflowLoading({
            tabId: tabId,
            message: getRunningMessage(tabId, st),
            steps: st.progress || presetSteps("confirm_start", "start"),
        });
        try {
            var res = await apiFetch(["/api/chatbot/workflows/start", "/chatbot/workflows/start"], {
                method: "POST",
                headers: authHeaders(),
                body: JSON.stringify({ workflow_id: st.workflowId }),
            });
            var data = await res.json().catch(function () {
                return {};
            });
            if (!res.ok) {
                var msg = parseApiErrorDetail(data) || "HTTP " + res.status;
                if (res.status === 402) msg = insufficientCreditText(data.detail || data);
                throw new Error(msg);
            }
            st.phase = "running";
            st.progress = data.progress || [];
            updateWorkflowProgress({
                tabId: tabId,
                cardId: cardId,
                message: getRunningMessage(tabId, st),
                steps: st.progress,
            });
            renderTabPanel(tabId);
            pollWorkflow(tabId, st.workflowId);
        } catch (err) {
            st.pendingRetry = function () {
                startWorkflow(tabId);
            };
            showWorkflowError({
                tabId: tabId,
                cardId: cardId,
                message: err.message || String(err),
            });
        }
    }

    function setTabHintVisible(show) {
        var hint = document.getElementById("gcbTabHint");
        if (hint) hint.hidden = !show;
    }

    function renderTabPanel(tabId) {
        var panel = document.querySelector('[data-gcb-panel="' + tabId + '"]');
        if (!panel) return;
        var st = getWorkflowState(tabId);
        var sections = {
            cards: panel.querySelector('[data-gcb-section="cards"]'),
            form: panel.querySelector('[data-gcb-section="form"]'),
            outline: panel.querySelector('[data-gcb-section="outline"]'),
            confirm: panel.querySelector('[data-gcb-section="confirm"]'),
            stage: panel.querySelector('[data-gcb-section="stage"]'),
            result: panel.querySelector('[data-gcb-section="result"]'),
        };
        Object.keys(sections).forEach(function (k) {
            if (sections[k]) sections[k].hidden = true;
        });

        if (!st.tabRevealed || st.phase === "idle") {
            return;
        }

        var visiblePhase = st.phase;
        if (st.phase === "error") {
            visiblePhase = st.returnPhase || "form";
        } else if (st.phase === "running") {
            visiblePhase = st.returnPhase || "confirm";
        }

        Object.keys(sections).forEach(function (k) {
            if (k === "stage" || k === "result") return;
            if (sections[k]) sections[k].hidden = visiblePhase !== k;
        });

        if (st.phase === "cards") {
            var cardsWrap = sections.cards && sections.cards.querySelector(".gcb-cards");
            if (!cardsWrap) return;
            cardsWrap.innerHTML = "";
            var tab = (window._gcbTabs || []).find(function (t) {
                return t.id === tabId;
            });
            (tab && tab.workflows ? tab.workflows : []).forEach(function (wf) {
                var card = document.createElement("button");
                card.type = "button";
                card.className = "gcb-card";
                card.innerHTML =
                    "<strong>" + esc(wf.title) + "</strong><span>" + esc(wf.description || "") + "</span>";
                card.addEventListener("click", function () {
                    st.phase = "form";
                    st.intent = wf.id;
                    renderTabPanel(tabId);
                    renderFormFields(tabId, wf.id, sections.form);
                });
                cardsWrap.appendChild(card);
            });
        }

        if (visiblePhase === "form" && st.intent && sections.form) {
            if (!sections.form.querySelector(".gcb-form")) {
                sections.form.innerHTML = "";
                renderFormFields(tabId, st.intent, sections.form);
            } else if (st.formParams && isWriteIntent(st.intent)) {
                prefillWriteForm(sections.form.querySelector(".gcb-form"), st.formParams);
            }
        }

        if (visiblePhase === "outline" && sections.outline) {
            renderOutlinePanel(tabId, sections.outline);
        }

        if (visiblePhase === "confirm" && sections.confirm && st.prepare) {
            var prep = st.prepare;
            sections.confirm.innerHTML =
                '<div class="gcb-confirm">' +
                '<p class="gcb-confirm-title">Xác nhận chạy workflow</p>' +
                '<p class="gcb-credit-estimate">' + esc(creditEstimateText(prep)) + "</p>" +
                '<ul class="gcb-credits">' +
                renderCreditLines(prep.credits || {}) +
                "</ul>" +
                '<p class="gcb-credits-total">Tổng: <strong>' +
                esc(String((prep.credits && prep.credits.total) || 0)) +
                "</strong> credit · Số dư: <strong>" +
                esc(String(prep.balance || 0)) +
                "</strong></p>" +
                (prep.sufficient
                    ? ""
                    : '<p class="gcb-error">' + esc(insufficientCreditText(prep)) + "</p>") +
                '<div class="gcb-form-actions">' +
                '<button type="button" class="gcb-btn gcb-btn--ghost" data-gcb-back>← Sửa form</button>' +
                '<button type="button" class="gcb-btn gcb-btn--primary" data-gcb-run ' +
                (prep.sufficient ? "" : "disabled") +
                ">Xác nhận & chạy</button>" +
                "</div></div>";
            sections.confirm.querySelector("[data-gcb-back]").addEventListener("click", function () {
                st.phase = "form";
                renderTabPanel(tabId);
            });
            sections.confirm.querySelector("[data-gcb-run]").addEventListener("click", function () {
                startWorkflow(tabId);
            });
        }

        if (st.phase === "running" && sections.stage) {
            sections.stage.hidden = false;
            setPanelLoading(tabId, true);
            if (!sections.stage.querySelector('[data-gcb-wf-card="loading"]')) {
                showWorkflowLoading({
                    tabId: tabId,
                    message: getRunningMessage(tabId, st),
                    steps: st.progress || [],
                });
            } else {
                updateWorkflowProgress({
                    tabId: tabId,
                    message: getRunningMessage(tabId, st),
                    steps: st.progress || [],
                });
            }
            setWorkflowBusy(tabId, true);
        } else if (st.phase === "error" && sections.stage) {
            sections.stage.hidden = false;
            if (!sections.stage.querySelector('[data-gcb-wf-card="error"]')) {
                sections.stage.innerHTML = buildErrorCardHtml(st.errorMessage || "Đã xảy ra lỗi.");
                bindWorkflowRetry(sections.stage, function () {
                    runWorkflowRetry(tabId);
                });
            }
        }

        if (st.phase === "result" && sections.result) {
            hideWorkflowLoading({ tabId: tabId });
            renderResult(sections.result, st.result || {});
        }
    }

    function buildChatPanelHtml() {
        return (
            '<div class="gcb-chat-panel">' +
            '<div class="digiseo-chatbot-messages" id="digiseoChatbotMessages" role="log" aria-live="polite"></div>' +
            '<div class="digiseo-chatbot-quick-wrap">' +
            '<div class="digiseo-chatbot-quick-bar">' +
            '<button type="button" class="digiseo-chatbot-quick-toggle" id="digiseoChatbotQuickToggle" aria-expanded="false" aria-controls="digiseoChatbotQuickPopup">' +
            "Hiển thị câu hỏi nhanh" +
            "</button></div>" +
            '<div class="digiseo-chatbot-quick-popup" id="digiseoChatbotQuickPopup" hidden role="dialog" aria-label="Câu hỏi nhanh">' +
            '<div class="digiseo-chatbot-quick-popup__head">' +
            "<strong>Câu hỏi nhanh</strong>" +
            '<button type="button" class="digiseo-chatbot-quick-popup__close" id="digiseoChatbotQuickClose" aria-label="Đóng">×</button>' +
            "</div>" +
            '<div class="digiseo-chatbot-quick" id="digiseoChatbotQuick"></div>' +
            "</div></div></div>"
        );
    }

    function buildPanels(workflowTabs) {
        var nav = document.getElementById("gcbTabs");
        var host = document.getElementById("gcbPanels");
        if (!nav || !host) return;
        nav.innerHTML = "";
        host.innerHTML = "";
        var hint = document.createElement("p");
        hint.className = "gcb-tab-hint";
        hint.id = "gcbTabHint";
        hint.textContent = "Chọn tab phía trên để xem tính năng workflow";
        host.appendChild(hint);
        window._gcbTabs = workflowTabs || [];

        function addTabButton(tabId, label) {
            var btn = document.createElement("button");
            btn.type = "button";
            btn.className = "gcb-tab";
            btn.setAttribute("role", "tab");
            btn.setAttribute("aria-selected", "false");
            btn.dataset.tab = tabId;
            btn.textContent = label;
            btn.addEventListener("click", function () {
                switchTab(tabId);
            });
            nav.appendChild(btn);
        }

        addTabButton(CHAT_TAB_ID, "Chat");
        var chatPanel = document.createElement(TAG_DIV);
        chatPanel.className = "gcb-tab-panel gcb-tab-panel--chat";
        chatPanel.dataset.gcbPanel = CHAT_TAB_ID;
        chatPanel.hidden = true;
        chatPanel.innerHTML = buildChatPanelHtml();
        host.appendChild(chatPanel);

        (workflowTabs || []).forEach(function (tab) {
            addTabButton(tab.id, tab.label);
            var panel = document.createElement(TAG_DIV);
            panel.className = "gcb-tab-panel";
            panel.dataset.gcbPanel = tab.id;
            panel.hidden = true;
            panel.innerHTML =
                '<section class="gcb-section" data-gcb-section="cards" hidden><div class="gcb-cards"></div></section>' +
                '<section class="gcb-section" data-gcb-section="form" hidden></section>' +
                '<section class="gcb-section" data-gcb-section="outline" data-gcb-panel-scope="' +
                tab.id +
                '" hidden></section>' +
                '<section class="gcb-section" data-gcb-section="confirm" hidden></section>' +
                '<section class="gcb-section gcb-section--stage" data-gcb-section="stage" hidden></section>' +
                '<section class="gcb-section" data-gcb-section="result" hidden></section>';
            host.appendChild(panel);
            workflowState[tab.id] = defaultWorkflowState();
        });

        bindChatUi();
        switchTab(CHAT_TAB_ID);
    }

    function switchTab(tabId) {
        tabId = String(tabId || CHAT_TAB_ID);
        if (isChatTabActive() && tabId !== CHAT_TAB_ID) {
            saveChatDraft();
        }

        activeTab = tabId;
        var isChat = tabId === CHAT_TAB_ID;

        setChatFooterVisible(isChat);
        setTabHintVisible(!isChat && !(getWorkflowState(tabId) && getWorkflowState(tabId).tabRevealed));

        document.querySelectorAll(".gcb-tab").forEach(function (btn) {
            var on = btn.dataset.tab === tabId;
            btn.classList.toggle("is-active", on);
            btn.setAttribute("aria-selected", on ? "true" : "false");
        });
        document.querySelectorAll(".gcb-tab-panel").forEach(function (p) {
            p.hidden = p.dataset.gcbPanel !== tabId;
        });

        updateGuestNoticeForTab();

        if (isChat) {
            restoreChatDraft();
            initChatWelcome();
            var input = document.getElementById("digiseoChatbotInput");
            if (input) setTimeout(function () { input.focus(); }, 80);
            return;
        }

        if (!getToken()) {
            return;
        }

        setTabHintVisible(false);
        var st = getWorkflowState(tabId);
        if (!st) return;
        st.tabRevealed = true;
        if (st.phase === "idle") {
            st.phase = "cards";
        }
        renderTabPanel(tabId);
    }

    async function loadTabs() {
        try {
            var res = await apiFetch(["/api/chatbot/tabs", "/chatbot/tabs"], { headers: authHeaders({}) });
            if (res.ok) {
                var data = await res.json();
                if (data.tabs && data.tabs.length) {
                    buildPanels(data.tabs);
                    return;
                }
            }
        } catch (_) {}
        buildPanels(FALLBACK_TABS);
    }

    function bind() {
        var root = document.getElementById(ROOT_ID);
        if (!root || root.dataset.bound) return;
        root.dataset.bound = "1";

        document.getElementById("digiseoChatbotFab").addEventListener("click", function () {
            setOpen(true);
            showGuestNotice(!getToken());
        });
        document.getElementById("digiseoChatbotClose").addEventListener("click", function () {
            setOpen(false);
            stopPoll();
            if (voiceRecognition && isListening) voiceRecognition.stop();
            stopVoiceInput();
        });

        loadTabs();
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", bind);
    } else {
        bind();
    }
})();
