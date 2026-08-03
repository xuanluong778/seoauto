/* Keyword Cluster SaaS UI — Content Map → Content AI */

(function (global) {
    "use strict";

    var state = {
        clusters: [],
        contentPlans: [],
        planEdits: {},
        selected: new Set(),
        mapSelected: new Set(),
        activeTab: "clusters",
        payload: null,
        drawerClusterId: null,
        drawerSort: { key: "volume", dir: -1 },
        drawerFilter: "",
    };

    function esc(s) {
        return String(s == null ? "" : s)
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/"/g, "&quot;");
    }

    function fmtNum(n) {
        var x = Number(n);
        if (!isFinite(x)) return "—";
        if (x >= 1e6) return (x / 1e6).toFixed(1) + "M";
        if (x >= 1e4) return Math.round(x / 1000) + "K";
        return String(Math.round(x)).replace(/\B(?=(\d{3})+(?!\d))/g, ",");
    }

    function fmtVol(v) {
        return v == null || v === "" ? "—" : fmtNum(v);
    }

    function fmtPct(v) {
        if (v == null || v === "") return "—";
        var x = Number(v);
        if (!isFinite(x)) return "—";
        if (x <= 1) return Math.round(x * 100) + "%";
        return Math.round(x) + "%";
    }

    function intentLabel(i) {
        var m = {
            informational: "Informational",
            commercial: "Commercial",
            transactional: "Transactional",
            navigational: "Navigational",
            local: "Local",
            mixed_intent: "Mixed",
        };
        return m[String(i || "").toLowerCase()] || "Informational";
    }

    function intentBadgeHtml(i) {
        var key = String(i || "informational").toLowerCase();
        var letter = "I";
        var cls = "kc-badge--i";
        if (key === "commercial" || key === "ecommerce") { letter = "C"; cls = "kc-badge--c"; }
        else if (key === "transactional") { letter = "T"; cls = "kc-badge--t"; }
        else if (key === "navigational") { letter = "N"; cls = "kc-badge--n"; }
        else if (key === "local") { letter = "L"; cls = "kc-badge--l"; }
        else if (key === "mixed_intent") { letter = "M"; cls = "kc-badge--m"; }
        return "<span class=\"kc-badge kc-badge--intent " + cls + "\" title=\"" + esc(intentLabel(key)) + "\">" + letter + "</span>";
    }

    function contentTypeLabel(t) {
        var s = String(t || "").toLowerCase();
        if (!s) return "—";
        var m = {
            long_form_article_or_guide: "Bài hướng dẫn",
            informational_article: "Bài thông tin",
            comparison_or_roundup: "So sánh / tổng hợp",
            comparison_buying_guide: "Hướng dẫn mua",
            conversion_focused_landing: "Landing chuyển đổi",
            product_or_collection_landing: "Trang sản phẩm",
            pillar_or_hub_page: "Trụ cột / hub",
            brand_or_resource_hub: "Thương hiệu / tài nguyên",
            video_script_or_embedded_article: "Video / bài nhúng",
        };
        if (m[s]) return m[s];
        return contentTypeShort(s.replace(/_/g, " "));
    }

    function showToast(message, type) {
        var host = document.getElementById("kcToastHost");
        if (!host) return;
        var el = document.createElement("div");
        el.className = "kc-toast kc-toast--" + (type || "info");
        el.textContent = String(message || "");
        host.appendChild(el);
        requestAnimationFrame(function () { el.classList.add("is-visible"); });
        setTimeout(function () {
            el.classList.remove("is-visible");
            setTimeout(function () { if (el.parentNode) el.parentNode.removeChild(el); }, 300);
        }, 4200);
    }

    function setLoading(on) {
        var sk = document.getElementById("kcSkeleton");
        var panel = document.getElementById("panel");
        if (sk) sk.hidden = !on;
        if (panel && on) panel.hidden = false;
    }

    function renderEmptyState(host, opts) {
        if (!host) return;
        var o = opts || {};
        host.innerHTML =
            "<div class=\"kc-empty\">" +
            "<div class=\"kc-empty-icon\" aria-hidden=\"true\">" + esc(o.icon || "📋") + "</div>" +
            "<h3 class=\"kc-empty-title\">" + esc(o.title || "Chưa có dữ liệu") + "</h3>" +
            "<p class=\"kc-empty-text\">" + esc(o.text || "Nhập từ khóa và chạy gom nhóm để xem kết quả.") + "</p>" +
            "</div>";
    }

    function friendlyStatus(msg, pct, state) {
        var m = String(msg || "").toLowerCase();
        var p = Number(pct) || 0;
        if (p >= 100 || m.indexOf("hoàn") >= 0 || m.indexOf("complete") >= 0 || m.indexOf("xong") >= 0) return "Hoàn tất";
        if (m.indexOf("content map") >= 0 || (p >= 93 && m.indexOf("tổng hợp") >= 0)) return "Đang tạo Content Map";
        if (m.indexOf("serp") >= 0 || m.indexOf("fetch") >= 0 && m.indexOf("keyword") >= 0) return "Đang phân tích SERP";
        if (m.indexOf("volume") >= 0) return "Đang lấy volume";
        if (m.indexOf("intent") >= 0 && p < 84) return "Đang phân loại ý định";
        if (m.indexOf("gom") >= 0 || m.indexOf("cluster") >= 0 || m.indexOf("union") >= 0 || m.indexOf("jaccard") >= 0) return "Đang gom nhóm";
        if (state === "QUEUED" || state === "PENDING") return "Đang chờ xử lý…";
        return "Đang xử lý…";
    }

    function roleLabel(r) {
        var m = {
            primary: "Chính",
            secondary: "Phụ",
            semantic: "Ngữ nghĩa",
            faq: "FAQ",
            supporting: "Hỗ trợ",
        };
        return m[r] || r || "—";
    }

    function priorityLabel(p) {
        if (p === "high") return "Cao";
        if (p === "medium") return "Trung bình";
        if (p === "low") return "Thấp";
        return "—";
    }

    function contentTypeShort(t) {
        var s = String(t || "");
        if (s.length <= 28) return s || "—";
        return s.slice(0, 27) + "…";
    }

    function priorityClass(score) {
        var x = Number(score);
        if (!isFinite(x)) return "";
        if (x >= 72) return "is-high";
        if (x >= 48) return "is-mid";
        return "is-low";
    }

    function getClusterById(id) {
        return state.clusters.find(function (c) { return c.cluster_id === id; }) || null;
    }

    function getPlanForCluster(clusterId) {
        var base = state.contentPlans.find(function (p) { return p.cluster_id === clusterId; });
        if (!base) {
            var c = getClusterById(clusterId);
            if (c && c.content_plan) base = c.content_plan;
        }
        if (!base) return null;
        var edits = state.planEdits[clusterId] || {};
        return Object.assign({}, base, edits);
    }

    function syncContentPlans() {
        state.contentPlans = state.clusters.map(function (c) {
            var p = c.content_plan;
            if (!p) {
                p = {
                    plan_id: "plan_" + c.cluster_id,
                    cluster_id: c.cluster_id,
                    topic: c.topic || c.main_keyword,
                    primary_keyword: c.main_keyword || c.primary_keyword,
                    secondary_keywords: [],
                    semantic_keywords: [],
                    faq_keywords: [],
                    intent: c.intent,
                    suggested_content_type: c.suggested_content_type,
                    content_angle: c.content_angle,
                    priority_score: c.confidence_score,
                    target_word_count: 1600,
                    recommended_title: c.main_keyword,
                    meta_description: "",
                    outline: (c.detail && c.detail.content_map && c.detail.content_map.outline_hint) || "",
                };
            }
            return Object.assign({}, p);
        });
    }

    function switchTab(tab) {
        state.activeTab = tab;
        document.querySelectorAll(".kc-tab").forEach(function (btn) {
            var on = btn.getAttribute("data-tab") === tab;
            btn.classList.toggle("is-active", on);
            btn.setAttribute("aria-selected", on ? "true" : "false");
        });
        var paneClusters = document.getElementById("kcPaneClusters");
        var paneMap = document.getElementById("kcPaneContentMap");
        if (paneClusters) {
            paneClusters.classList.toggle("is-active", tab === "clusters");
            paneClusters.hidden = tab !== "clusters";
        }
        if (paneMap) {
            paneMap.classList.toggle("is-active", tab === "contentmap");
            paneMap.hidden = tab !== "contentmap";
        }
        if (tab === "contentmap") renderContentMapTable();
    }

    function renderContentMapTable() {
        var tbody = document.getElementById("kcContentMapBody");
        if (!tbody) return;
        if (!state.contentPlans.length) {
            tbody.innerHTML = "<tr><td colspan=\"8\"><div class=\"kc-empty kc-empty--inline\">" +
                "<p class=\"kc-empty-title\">Chưa có bản đồ nội dung</p>" +
                "<p class=\"kc-empty-text\">Gom nhóm xong để tự động tạo kế hoạch bài viết cho từng cụm.</p>" +
                "</div></td></tr>";
            updateMapToolbar();
            return;
        }
        tbody.innerHTML = state.contentPlans.map(function (base) {
            var id = base.cluster_id;
            var p = getPlanForCluster(id) || base;
            var c = getClusterById(id);
            var vol = c ? clusterTotalVol(c) : null;
            var pri = p.priority_score != null ? p.priority_score : "—";
            var priCls = priorityClass(p.priority_score);
            return "<tr data-plan-id=\"" + esc(id) + "\">" +
                "<td class=\"kc-col-check\"><input type=\"checkbox\" class=\"kc-map-row-check\" data-id=\"" + esc(id) + "\"" +
                (state.mapSelected.has(id) ? " checked" : "") + " /></td>" +
                "<td><span class=\"kc-map-topic\" title=\"" + esc(p.topic) + "\">" + esc(p.topic) + "</span></td>" +
                "<td><span class=\"kc-map-kw\" title=\"" + esc(p.primary_keyword) + "\">" + esc(p.primary_keyword) + "</span></td>" +
                "<td class=\"kc-col-num\">" + fmtVol(vol) + "</td>" +
                "<td>" + intentBadgeHtml(p.intent) + "</td>" +
                "<td><span class=\"kc-map-type\" title=\"" + esc(p.suggested_content_type) + "\">" + esc(contentTypeLabel(p.suggested_content_type)) + "</span></td>" +
                "<td class=\"kc-col-num\"><span class=\"kc-priority-pill " + priCls + "\">" + esc(String(pri)) + "</span></td>" +
                "<td class=\"kc-col-actions\"><div class=\"kc-map-actions\">" +
                "<button type=\"button\" class=\"kc-btn kc-btn--ghost kc-map-view\" data-id=\"" + esc(id) + "\">Xem cụm</button>" +
                "<button type=\"button\" class=\"kc-btn kc-btn--ghost kc-map-brief\" data-id=\"" + esc(id) + "\">Sửa brief</button>" +
                "<button type=\"button\" class=\"kc-btn kc-btn--primary kc-map-write\" data-id=\"" + esc(id) + "\">Viết 1 bài</button>" +
                "<button type=\"button\" class=\"kc-btn kc-btn--ghost kc-map-add\" data-id=\"" + esc(id) + "\">Thêm hàng loạt</button>" +
                "</div></td></tr>";
        }).join("");
        bindContentMapEvents();
        updateMapToolbar();
    }

    function bindContentMapEvents() {
        document.querySelectorAll(".kc-map-row-check").forEach(function (cb) {
            cb.onchange = function () {
                var id = cb.getAttribute("data-id");
                if (!id) return;
                if (cb.checked) state.mapSelected.add(id);
                else state.mapSelected.delete(id);
                updateMapToolbar();
            };
        });
        document.querySelectorAll(".kc-map-view").forEach(function (btn) {
            btn.onclick = function () {
                switchTab("clusters");
                openDrawer(btn.getAttribute("data-id"));
            };
        });
        document.querySelectorAll(".kc-map-brief").forEach(function (btn) {
            btn.onclick = function () { openBriefModal(btn.getAttribute("data-id")); };
        });
        document.querySelectorAll(".kc-map-write").forEach(function (btn) {
            btn.onclick = function () { writeSingle(btn.getAttribute("data-id")); };
        });
        document.querySelectorAll(".kc-map-add").forEach(function (btn) {
            btn.onclick = function () {
                var id = btn.getAttribute("data-id");
                if (id) state.mapSelected.add(id);
                openContentMapModal();
            };
        });
    }

    function updateMapToolbar() {
        var n = state.mapSelected.size;
        var lbl = document.getElementById("kcMapSelectedCount");
        if (lbl) lbl.textContent = n + " kế hoạch đã chọn";
        var btn = document.getElementById("kcMapBulkWrite");
        if (btn) btn.disabled = n === 0;
    }

    function openBriefModal(clusterId) {
        var p = getPlanForCluster(clusterId);
        if (!p) return;
        document.getElementById("kcBriefPlanId").value = clusterId;
        document.getElementById("kcBriefTitleInput").value = p.recommended_title || "";
        document.getElementById("kcBriefContentType").value = p.suggested_content_type || "";
        document.getElementById("kcBriefWordCount").value = String(p.target_word_count || 1600);
        document.getElementById("kcBriefMeta").value = p.meta_description || "";
        document.getElementById("kcBriefOutline").value = p.outline || "";
        var modal = document.getElementById("kcBriefModal");
        var bd = document.getElementById("kcBriefBackdrop");
        if (modal) { modal.classList.add("is-open"); modal.setAttribute("aria-hidden", "false"); }
        if (bd) bd.classList.add("is-open");
    }

    function closeBriefModal() {
        var modal = document.getElementById("kcBriefModal");
        var bd = document.getElementById("kcBriefBackdrop");
        if (modal) { modal.classList.remove("is-open"); modal.setAttribute("aria-hidden", "true"); }
        if (bd) bd.classList.remove("is-open");
    }

    function saveBriefModal() {
        var id = document.getElementById("kcBriefPlanId").value;
        if (!id) return;
        state.planEdits[id] = {
            recommended_title: document.getElementById("kcBriefTitleInput").value.trim(),
            suggested_content_type: document.getElementById("kcBriefContentType").value.trim(),
            target_word_count: parseInt(document.getElementById("kcBriefWordCount").value, 10) || 1600,
            meta_description: document.getElementById("kcBriefMeta").value.trim(),
            outline: document.getElementById("kcBriefOutline").value.trim(),
        };
        closeBriefModal();
        renderContentMapTable();
    }

    function keywordText(k) {
        if (k == null) return "";
        if (typeof k === "string") return k.trim();
        if (typeof k === "object") return String(k.keyword || k.text || "").trim();
        return String(k).trim();
    }

    function collectSecondaryKeywords(c, p) {
        var main = keywordText((p && p.primary_keyword) || (c && c.main_keyword) || (c && c.primary_keyword)).toLowerCase();
        var clusterIntent = String((p && p.intent) || (c && c.intent) || "").trim().toLowerCase();
        var buckets = [];
        function addList(list) {
            if (!list) return;
            buckets.push(Array.isArray(list) ? list : [list]);
        }
        if (p) {
            addList(p.secondary_keywords);
            addList(p.semantic_keywords);
            addList(p.keywords);
            addList(p.variations);
        }
        if (c) {
            addList(c.supporting_keywords);
            addList(c.keywords);
            addList(c.variations);
            if (Array.isArray(c.keyword_items)) {
                addList(c.keyword_items.map(function (it) { return it && (it.keyword || it.text); }));
            }
        }
        var seen = {};
        var out = [];
        buckets.forEach(function (list) {
            (list || []).forEach(function (item) {
                var k = keywordText(item);
                if (!k) return;
                var lk = k.toLowerCase();
                if (lk === main || seen[lk]) return;
                if (clusterIntent && Array.isArray(c && c.keyword_items)) {
                    var row = c.keyword_items.find(function (it) {
                        return String((it && it.keyword) || "").trim().toLowerCase() === lk;
                    });
                    if (row && row.intent && String(row.intent).toLowerCase() !== clusterIntent) return;
                }
                seen[lk] = true;
                out.push(k);
            });
        });
        return out;
    }

    function isRawJsonOutline(s) {
        s = String(s || "").trim();
        if (!s) return false;
        var first = s.charAt(0);
        var last = s.charAt(s.length - 1);
        if ((first === "{" && last === "}") || (first === "[" && last === "]")) {
            try {
                JSON.parse(s);
                return true;
            } catch (_e) {}
        }
        return false;
    }

    function generateSeoOutline(mainKw, topic, intent, contentType, secKws) {
        var title = String(topic || mainKw || "").trim();
        var mk = String(mainKw || topic || "").trim();
        var it = String(intent || "").toLowerCase();
        var lines = ["H1: " + title, ""];
        if (it === "informational") {
            if (mk) lines.push("H2: " + mk + " là gì?");
        } else if (it === "commercial" || it === "transactional" || it === "local") {
            lines.push("H2: Giới thiệu " + (mk || "dịch vụ"));
            lines.push("H2: Lợi ích & quy trình");
        } else if (mk) {
            lines.push("H2: " + mk);
        }
        if (secKws && secKws.length) {
            lines.push("H2: " + (contentType ? contentType + " — " : "Chi tiết về ") + mk);
            secKws.slice(0, 6).forEach(function (kw) {
                lines.push("  H3: " + kw);
            });
        }
        lines.push("H2: Lợi ích và ứng dụng");
        if (secKws && secKws.length > 6) {
            lines.push("H2: Câu hỏi thường gặp");
            secKws.slice(6, 10).forEach(function (kw) {
                lines.push("  - " + kw);
            });
        }
        lines.push("H2: Kết luận");
        var meta = [];
        if (intent) meta.push("Intent: " + intent);
        if (contentType) meta.push("Loại bài: " + contentType);
        if (meta.length) {
            lines.push("");
            lines.push(meta.join(" · "));
        }
        return lines.join("\n").trim();
    }

    function resolveClusterOutline(p, c, secKws) {
        var mainKw = keywordText((p && p.primary_keyword) || (c && c.main_keyword) || (c && c.primary_keyword));
        var topic = String((p && (p.topic || p.recommended_title)) || (c && c.topic) || mainKw).trim();
        var intent = String((p && p.intent) || (c && c.intent) || "").trim();
        var contentType = String((p && p.suggested_content_type) || (c && c.suggested_content_type) || "").trim();
        var sec = secKws || collectSecondaryKeywords(c, p);
        var candidates = [];
        if (p && p.outline) candidates.push(p.outline);
        if (p && p.content_angle) candidates.push(p.content_angle);
        if (c && c.content_angle) candidates.push(c.content_angle);
        if (c && c.detail && c.detail.content_map && c.detail.content_map.outline_hint) {
            candidates.push(c.detail.content_map.outline_hint);
        }
        for (var i = 0; i < candidates.length; i++) {
            var raw = String(candidates[i] || "").trim();
            if (raw && !isRawJsonOutline(raw)) return raw;
        }
        return generateSeoOutline(mainKw, topic, intent, contentType, sec);
    }

    function saveContentAiPrefill(payload) {
        try {
            sessionStorage.setItem("seoauto_content_ai_prefill", JSON.stringify(payload));
        } catch (_e) {}
    }

    function planToPrefill(p, c) {
        var main = keywordText(p.primary_keyword || (c && c.main_keyword) || "");
        var sec = collectSecondaryKeywords(c, p);
        var outline = resolveClusterOutline(p, c, sec);
        return {
            primary_keyword: main,
            main_keyword: main,
            secondary_keywords: sec,
            keywords: sec,
            supporting_keywords: sec,
            topic: p.topic || (c && c.topic) || "",
            intent: p.intent || (c && c.intent) || "",
            content_type: p.suggested_content_type || (c && c.suggested_content_type) || "",
            custom_outline: outline,
            outline: outline,
            content_angle: p.content_angle || (c && c.content_angle) || "",
            recommended_title: p.recommended_title || p.topic || (c && c.topic) || "",
            meta_description: p.meta_description || "",
            search_volume: clusterTotalVol(c),
            target_word_count: p.target_word_count || 1600,
            target_website: (document.getElementById("brandUrl") && document.getElementById("brandUrl").value.trim()) || "",
        };
    }

    function planToBulkItem(p, c) {
        var sec = collectSecondaryKeywords(c, p);
        var intent = String(p.intent || (c && c.intent) || "").trim();
        var outline = resolveClusterOutline(p, c, sec);
        return {
            keyword: keywordText(p.primary_keyword || (c && c.main_keyword) || ""),
            custom_title: p.recommended_title || p.topic || (c && c.topic) || "",
            custom_description: p.meta_description || (intent ? "Search intent: " + intent : ""),
            custom_outline: outline,
            search_volume: clusterTotalVol(c),
            content_type: p.suggested_content_type || (c && c.suggested_content_type) || "",
            secondary_keywords: sec.join(", "),
            intent: intent,
            target_word_count: p.target_word_count || 1600,
        };
    }

    function clusterToBulkItem(c) {
        var p = getPlanForCluster(c.cluster_id);
        if (p) return planToBulkItem(p, c);
        var sec = collectSecondaryKeywords(c, null);
        var intent = String(c.intent || "").trim();
        var outline = resolveClusterOutline(null, c, sec);
        return {
            keyword: keywordText(c.main_keyword || c.primary_keyword || ""),
            custom_title: c.topic || c.main_keyword || "",
            custom_description: intent ? "Search intent: " + intent : "",
            custom_outline: outline,
            search_volume: clusterTotalVol(c),
            content_type: c.suggested_content_type || "",
            secondary_keywords: sec.join(", "),
            intent: intent,
            target_word_count: 1600,
        };
    }


    function clusterTotalVol(c) {
        if (c.total_volume != null) return c.total_volume;
        return null;
    }

    function drawChart(topics) {
        var card = document.getElementById("kcChartCard");
        var wrap = document.getElementById("kcChartWrap");
        if (!card || !wrap) return;
        wrap.innerHTML = "";
        if (!topics || !topics.length) {
            card.hidden = true;
            return;
        }
        card.hidden = false;
        var W = Math.max(720, Math.min(1100, topics.length * 96));
        var H = 220;
        var pad = { l: 48, r: 12, t: 16, b: 56 };
        var innerW = W - pad.l - pad.r;
        var innerH = H - pad.t - pad.b;
        var maxVal = Math.max.apply(null, topics.map(function (t) { return t.vol || 0; }).concat([1]));
        var svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
        svg.setAttribute("viewBox", "0 0 " + W + " " + H);
        svg.setAttribute("width", "100%");
        svg.setAttribute("height", String(H));
        svg.setAttribute("role", "img");
        svg.setAttribute("aria-label", "Biểu đồ volume theo cụm");
        var g = document.createElementNS("http://www.w3.org/2000/svg", "g");
        g.setAttribute("transform", "translate(" + pad.l + "," + pad.t + ")");
        var slot = innerW / topics.length;
        var bw = slot * 0.55;
        topics.forEach(function (t, i) {
            var v = t.vol || 0;
            var h = innerH * (v / maxVal);
            var x = i * slot + (slot - bw) / 2;
            var rect = document.createElementNS("http://www.w3.org/2000/svg", "rect");
            rect.setAttribute("x", String(x));
            rect.setAttribute("y", String(innerH - h));
            rect.setAttribute("width", String(bw));
            rect.setAttribute("height", String(Math.max(2, h)));
            rect.setAttribute("rx", "5");
            rect.setAttribute("fill", "#6366f1");
            g.appendChild(rect);
            if (v > 0) {
                var val = document.createElementNS("http://www.w3.org/2000/svg", "text");
                val.setAttribute("x", String(x + bw / 2));
                val.setAttribute("y", String(Math.max(14, innerH - h - 8)));
                val.setAttribute("text-anchor", "middle");
                val.setAttribute("fill", "#e2e8f0");
                val.setAttribute("font-size", "10");
                val.textContent = fmtNum(v);
                g.appendChild(val);
            }
        });
        svg.appendChild(g);
        topics.forEach(function (t, i) {
            var x = pad.l + i * slot + slot / 2;
            var label = document.createElementNS("http://www.w3.org/2000/svg", "text");
            label.setAttribute("x", String(x));
            label.setAttribute("y", String(H - 28));
            label.setAttribute("text-anchor", "middle");
            label.setAttribute("fill", "#94a3b8");
            label.setAttribute("font-size", "10");
            var s = String(t.label || "");
            if (s.length > 18) s = s.slice(0, 17) + "…";
            label.textContent = s;
            svg.appendChild(label);
        });
        wrap.appendChild(svg);
    }

    function renderSummary(summary) {
        var s = summary || {};
        var set = function (id, val) {
            var el = document.getElementById(id);
            if (el) el.textContent = val;
        };
        set("kcSumClusters", String(s.cluster_count != null ? s.cluster_count : state.clusters.length));
        set("kcSumKeywords", String(s.total_keywords != null ? s.total_keywords : "—"));
        set("kcSumVolume", fmtVol(s.total_volume));
        set("kcSumArticles", String(s.articles_suggested != null ? s.articles_suggested : state.clusters.length));
    }

    function topKeywords(c, n) {
        var items = c.keyword_items || [];
        if (items.length) return items.slice(0, n || 5);
        return (c.keywords || []).slice(0, n || 5).map(function (k) { return { keyword: k, volume: null }; });
    }

    function renderGrid() {
        var host = document.getElementById("kcClusterGrid");
        if (!host) return;
        if (!state.clusters.length) {
            renderEmptyState(host, {
                icon: "🗂️",
                title: "Chưa có cụm từ khóa",
                text: "Kết quả gom nhóm sẽ hiển thị tại đây sau khi bạn chạy phân tích.",
            });
            return;
        }
        host.innerHTML = "";
        state.clusters.forEach(function (c) {
            var id = c.cluster_id;
            var card = document.createElement("article");
            card.className = "kc-card" + (state.selected.has(id) ? " is-selected" : "");
            card.setAttribute("data-cluster-id", id);
            var top5 = topKeywords(c, 5);
            var kwLines = top5.map(function (it) {
                return "<li>" + esc(it.keyword) + " <span class=\"kc-kw-vol\">" + fmtVol(it.volume) + "</span></li>";
            }).join("");
            card.innerHTML =
                "<div class=\"kc-card-head\">" +
                "<label class=\"kc-check\"><input type=\"checkbox\" class=\"kc-select\" data-id=\"" + esc(id) + "\"" +
                (state.selected.has(id) ? " checked" : "") + " /><span>Chọn</span></label>" +
                intentBadgeHtml(c.intent) +
                "</div>" +
                "<h3 class=\"kc-card-topic\" title=\"" + esc(c.topic || c.main_keyword) + "\">" + esc(c.topic || c.main_keyword) + "</h3>" +
                "<p class=\"kc-card-main\">" + esc(c.main_keyword || "") + "</p>" +
                "<div class=\"kc-card-stats\">" +
                "<div><span>Volume</span><strong>" + fmtVol(clusterTotalVol(c)) + "</strong></div>" +
                "<div><span>Từ khóa</span><strong>" + (c.total_keyword || (c.keywords || []).length) + "</strong></div>" +
                "<div><span>SERP chung</span><strong>" + (c.shared_urls_count != null ? c.shared_urls_count : "—") + "</strong></div>" +
                "<div><span>Tin cậy</span><strong>" + fmtPct(c.confidence_score != null ? c.confidence_score / 100 : null) + "</strong></div>" +
                "</div>" +
                (c.warning ? "<p class=\"kc-card-warning\">" + esc(c.warning) + "</p>" : "") +
                "<p class=\"kc-card-type\">" + esc(contentTypeLabel(c.suggested_content_type)) + "</p>" +
                "<ul class=\"kc-kw-preview\">" + kwLines + "</ul>" +
                "<div class=\"kc-card-actions\">" +
                "<button type=\"button\" class=\"kc-btn kc-btn--ghost kc-act-detail\" data-id=\"" + esc(id) + "\">Xem chi tiết</button>" +
                "<button type=\"button\" class=\"kc-btn kc-btn--primary kc-act-write\" data-id=\"" + esc(id) + "\">Viết 1 bài</button>" +
                "<button type=\"button\" class=\"kc-btn kc-btn--ghost kc-act-bulk\" data-id=\"" + esc(id) + "\">Thêm hàng loạt</button>" +
                "<button type=\"button\" class=\"kc-btn kc-btn--ghost kc-act-rank\" data-id=\"" + esc(id) + "\">Theo dõi Rank</button>" +
                "</div>";
            host.appendChild(card);
        });
        bindGridEvents();
        updateBulkToolbar();
    }

    function bindGridEvents() {
        document.querySelectorAll(".kc-select").forEach(function (cb) {
            cb.onchange = function () {
                var id = cb.getAttribute("data-id");
                if (!id) return;
                if (cb.checked) state.selected.add(id);
                else state.selected.delete(id);
                renderGrid();
            };
        });
        document.querySelectorAll(".kc-act-detail").forEach(function (btn) {
            btn.onclick = function () { openDrawer(btn.getAttribute("data-id")); };
        });
        document.querySelectorAll(".kc-act-write").forEach(function (btn) {
            btn.onclick = function () { writeSingle(btn.getAttribute("data-id")); };
        });
        document.querySelectorAll(".kc-act-bulk").forEach(function (btn) {
            btn.onclick = function () {
                state.selected.add(btn.getAttribute("data-id"));
                openContentMapModal();
            };
        });
        document.querySelectorAll(".kc-act-rank").forEach(function (btn) {
            btn.onclick = function () { trackRank(btn.getAttribute("data-id")); };
        });
    }

    function updateBulkToolbar() {
        var n = state.selected.size;
        var lbl = document.getElementById("kcSelectedCount");
        if (lbl) lbl.textContent = n + " cụm đã chọn";
        var btn = document.getElementById("kcBtnBulkWrite");
        if (btn) btn.disabled = n === 0;
    }

    function openDrawer(clusterId) {
        var c = getClusterById(clusterId);
        if (!c) return;
        state.drawerClusterId = clusterId;
        state.drawerFilter = "";
        state.drawerSort = { key: "volume", dir: -1 };
        var drawer = document.getElementById("kcDrawer");
        if (!drawer) return;
        var title = c.topic || c.main_keyword || "Chi tiết cụm từ khóa";
        var titleEl = document.getElementById("kcDrawerTitle");
        if (titleEl) titleEl.textContent = title;
        var topicEl = document.getElementById("kcDrawerTopic");
        if (topicEl) topicEl.textContent = c.topic || c.main_keyword || "—";
        var intentEl = document.getElementById("kcDrawerIntent");
        if (intentEl) intentEl.innerHTML = intentBadgeHtml(c.intent);
        var warnEl = document.getElementById("kcDrawerIntentWarn");
        if (warnEl) {
            if (c.intent_conflict) {
                warnEl.hidden = false;
                warnEl.textContent = "Có thể khác intent";
                warnEl.className = "kc-cluster-warn is-conflict";
            } else if (c.warning) {
                warnEl.hidden = false;
                warnEl.textContent = "Cần kiểm tra intent";
                warnEl.className = "kc-cluster-warn";
            } else {
                warnEl.hidden = true;
                warnEl.textContent = "";
            }
        }
        var volEl = document.getElementById("kcDrawerVolume");
        if (volEl) volEl.textContent = fmtVol(clusterTotalVol(c));
        var kwEl = document.getElementById("kcDrawerKwCount");
        if (kwEl) kwEl.textContent = String(c.total_keyword || (c.keyword_items || []).length);
        renderDrawerTable();
        drawer.classList.add("is-open");
        drawer.setAttribute("aria-hidden", "false");
        var bd = document.getElementById("kcDrawerBackdrop");
        if (bd) {
            bd.classList.add("is-open");
            bd.setAttribute("aria-hidden", "false");
        }
        document.body.style.overflow = "hidden";
    }

    function closeDrawer() {
        var drawer = document.getElementById("kcDrawer");
        if (drawer) {
            drawer.classList.remove("is-open");
            drawer.setAttribute("aria-hidden", "true");
        }
        var bd = document.getElementById("kcDrawerBackdrop");
        if (bd) {
            bd.classList.remove("is-open");
            bd.setAttribute("aria-hidden", "true");
        }
        document.body.style.overflow = "";
        state.drawerClusterId = null;
    }

    function sortedFilteredItems(c) {
        var items = (c.keyword_items || []).slice();
        var q = (state.drawerFilter || "").trim().toLowerCase();
        if (q) items = items.filter(function (it) { return String(it.keyword || "").toLowerCase().indexOf(q) >= 0; });
        var key = state.drawerSort.key;
        var dir = state.drawerSort.dir;
        items.sort(function (a, b) {
            function val(it) {
                if (key === "volume") return it.volume == null ? -1 : Number(it.volume);
                if (key === "matching") return it.matching_point == null ? -1 : Number(it.matching_point);
                if (key === "intent") return String(it.intent || "");
                return String(it.keyword || "");
            }
            var va = val(a), vb = val(b);
            if (va < vb) return -dir;
            if (va > vb) return dir;
            return 0;
        });
        return items;
    }

    function renderDrawerTable() {
        var c = getClusterById(state.drawerClusterId);
        var tbody = document.getElementById("kcDrawerTableBody");
        if (!c || !tbody) return;
        var items = sortedFilteredItems(c);
        tbody.innerHTML = items.map(function (it) {
            return "<tr>" +
                "<td class=\"kw-cell\">" + esc(it.keyword) + "</td>" +
                "<td class=\"num\">" + fmtVol(it.volume) + "</td>" +
                "<td class=\"num\">" + (it.matching_point != null ? it.matching_point : "—") + "</td>" +
                "</tr>";
        }).join("");
    }

    function exportDrawerCsv() {
        var c = getClusterById(state.drawerClusterId);
        if (!c) return;
        var items = sortedFilteredItems(c);
        var lines = ["Keyword,Volume,CPC,Competition,Intent,Matching,SERP overlap,Content role"];
        items.forEach(function (it) {
            lines.push([
                '"' + String(it.keyword || "").replace(/"/g, '""') + '"',
                it.volume != null ? it.volume : "",
                it.cpc != null ? it.cpc : "",
                '"' + String(it.competition || "").replace(/"/g, '""') + '"',
                it.intent || "",
                it.matching_point != null ? it.matching_point : "",
                it.serp_overlap != null ? it.serp_overlap : "",
                it.content_role || "",
            ].join(","));
        });
        var blob = new Blob([lines.join("\n")], { type: "text/csv;charset=utf-8" });
        var a = document.createElement("a");
        a.href = URL.createObjectURL(blob);
        a.download = "cluster-" + (c.main_keyword || "export").replace(/\W+/g, "-").slice(0, 40) + ".csv";
        a.click();
        URL.revokeObjectURL(a.href);
    }

    function clusterToSinglePrefill(c) {
        var p = getPlanForCluster(c.cluster_id);
        if (p) return planToPrefill(p, c);
        var main = keywordText(c.main_keyword || c.primary_keyword || "");
        var sec = collectSecondaryKeywords(c, null);
        var outline = resolveClusterOutline(null, c, sec);
        return {
            primary_keyword: main,
            main_keyword: main,
            secondary_keywords: sec,
            keywords: sec,
            supporting_keywords: sec,
            topic: c.topic || "",
            intent: c.intent || "",
            content_type: c.suggested_content_type || "",
            custom_outline: outline,
            outline: outline,
            content_angle: c.content_angle || "",
            recommended_title: c.topic || c.main_keyword || "",
            search_volume: clusterTotalVol(c),
            target_website: (document.getElementById("brandUrl") && document.getElementById("brandUrl").value.trim()) || "",
            target_word_count: 1600,
        };
    }

    function writeSingle(clusterId) {
        var c = getClusterById(clusterId);
        if (!c) return;
        saveContentAiPrefill({ mode: "single", data: clusterToSinglePrefill(c) });
        global.location.href = "/content-ai?mode=single";
    }

    function writeBulkSelected() {
        var clusters = selectedClusters();
        if (!clusters.length) return;
        var items = clusters.map(function (c) { return clusterToBulkItem(c); }).filter(function (it) { return it.keyword; });
        if (!items.length) return;
        var site = (document.getElementById("brandUrl") && document.getElementById("brandUrl").value.trim()) || "";
        saveContentAiPrefill({ mode: "bulk", target_website: site, items: items });
        global.location.href = "/content-ai?mode=bulk";
    }

    function trackRank(clusterId) {
        var c = getClusterById(clusterId);
        if (!c) return;
        var kws = (c.keyword_items || []).map(function (it) { return it.keyword; }).filter(Boolean);
        try {
            sessionStorage.setItem("seoauto_cluster_rank_prefill", JSON.stringify({ keywords: kws.slice(0, 50) }));
        } catch (_e) {}
        global.location.href = "/keywords/tools/rank-tracking";
    }

    function selectedClusters() {
        return state.clusters.filter(function (c) { return state.selected.has(c.cluster_id); });
    }

    function selectedPlansFromMap() {
        return state.contentPlans
            .filter(function (p) { return state.mapSelected.has(p.cluster_id); })
            .map(function (p) { return getPlanForCluster(p.cluster_id) || p; });
    }

    function openContentMapModal() {
        var list = selectedPlansFromMap();
        if (!list.length) list = selectedClusters().map(function (c) { return getPlanForCluster(c.cluster_id); }).filter(Boolean);
        if (!list.length) return;
        var host = document.getElementById("kcMapList");
        if (!host) return;
        host.innerHTML = list.map(function (p, i) {
            var c = getClusterById(p.cluster_id);
            var sec = (p.secondary_keywords || []).slice(0, 6).join(", ");
            return "<article class=\"kc-map-item\" data-map-idx=\"" + i + "\" data-id=\"" + esc(p.cluster_id) + "\">" +
                "<label class=\"kc-check\"><input type=\"checkbox\" class=\"kc-map-check\" checked data-id=\"" + esc(p.cluster_id) + "\" /><span>Bao gồm</span></label>" +
                "<div class=\"kc-map-grid\">" +
                "<div><span>Chủ đề</span><strong>" + esc(p.topic) + "</strong></div>" +
                "<div><span>Tiêu đề</span><input type=\"text\" class=\"kc-map-title\" data-id=\"" + esc(p.cluster_id) + "\" value=\"" + esc(p.recommended_title || p.primary_keyword || "") + "\" /></div>" +
                "<div><span>Keyword chính</span><strong>" + esc(p.primary_keyword) + "</strong></div>" +
                "<div><span>Từ khóa phụ</span><p class=\"kc-map-sup\">" + esc(sec || "—") + "</p></div>" +
                "<div><span>Intent</span><strong>" + esc(intentLabel(p.intent)) + "</strong></div>" +
                "<div><span>Loại bài</span><input type=\"text\" class=\"kc-map-ctype\" data-id=\"" + esc(p.cluster_id) + "\" value=\"" + esc(p.suggested_content_type || "") + "\" /></div>" +
                "<div><span>Volume</span><strong>" + fmtVol(c ? clusterTotalVol(c) : null) + "</strong></div>" +
                "<div><span>Số từ</span><input type=\"number\" class=\"kc-map-wc\" data-id=\"" + esc(p.cluster_id) + "\" value=\"" + esc(String(p.target_word_count || 1600)) + "\" min=\"800\" max=\"4500\" step=\"100\" /></div>" +
                "<div><span>Priority</span><strong>" + esc(String(p.priority_score != null ? p.priority_score : "—")) + "</strong></div>" +
                "</div>" +
                "<label class=\"kc-map-outline-label\">Outline<textarea class=\"kc-map-outline\" data-id=\"" + esc(p.cluster_id) + "\" rows=\"4\">" +
                esc(p.outline || "") + "</textarea></label>" +
                "</article>";
        }).join("");
        var modal = document.getElementById("kcContentMapModal");
        if (modal) {
            modal.classList.add("is-open");
            modal.setAttribute("aria-hidden", "false");
        }
        var bd = document.getElementById("kcMapBackdrop");
        if (bd) bd.classList.add("is-open");
    }

    function closeContentMapModal() {
        var modal = document.getElementById("kcContentMapModal");
        if (modal) {
            modal.classList.remove("is-open");
            modal.setAttribute("aria-hidden", "true");
        }
        var bd = document.getElementById("kcMapBackdrop");
        if (bd) bd.classList.remove("is-open");
    }

    function submitContentMapToBulk() {
        var items = [];
        document.querySelectorAll(".kc-map-item").forEach(function (row) {
            var id = row.getAttribute("data-id");
            var chk = row.querySelector(".kc-map-check");
            if (!chk || !chk.checked) return;
            var c = getClusterById(id);
            var p = getPlanForCluster(id);
            if (!p) return;
            var titleEl = row.querySelector(".kc-map-title");
            var ctypeEl = row.querySelector(".kc-map-ctype");
            var wcEl = row.querySelector(".kc-map-wc");
            var outlineEl = row.querySelector(".kc-map-outline");
            var merged = Object.assign({}, p, {
                recommended_title: (titleEl && titleEl.value.trim()) || p.recommended_title,
                suggested_content_type: (ctypeEl && ctypeEl.value.trim()) || p.suggested_content_type,
                target_word_count: parseInt((wcEl && wcEl.value) || p.target_word_count, 10) || 1600,
                outline: (outlineEl && outlineEl.value.trim()) || p.outline,
            });
            items.push(planToBulkItem(merged, c));
        });
        if (!items.length) return;
        var site = (document.getElementById("brandUrl") && document.getElementById("brandUrl").value.trim()) || "";
        saveContentAiPrefill({ mode: "bulk", target_website: site, items: items });
        closeContentMapModal();
        global.location.href = "/content-ai?mode=bulk";
    }

    function bindChrome() {
        var closeBtn = document.getElementById("kcDrawerClose");
        if (closeBtn) closeBtn.onclick = closeDrawer;
        var backdrop = document.getElementById("kcDrawerBackdrop");
        if (backdrop) backdrop.onclick = closeDrawer;
        document.addEventListener("keydown", function (e) {
            if (e.key === "Escape" && state.drawerClusterId) closeDrawer();
        });
        var mapClose = document.getElementById("kcMapClose");
        if (mapClose) mapClose.onclick = closeContentMapModal;
        var mapClose2 = document.getElementById("kcMapClose2");
        if (mapClose2) mapClose2.onclick = closeContentMapModal;
        var mapBackdrop = document.getElementById("kcMapBackdrop");
        if (mapBackdrop) mapBackdrop.onclick = closeContentMapModal;
        var mapSubmit = document.getElementById("kcMapSubmit");
        if (mapSubmit) mapSubmit.onclick = submitContentMapToBulk;
        var bulkBtn = document.getElementById("kcBtnBulkWrite");
        if (bulkBtn) bulkBtn.onclick = writeBulkSelected;
        var mapBulkBtn = document.getElementById("kcMapBulkWrite");
        if (mapBulkBtn) mapBulkBtn.onclick = openContentMapModal;
        document.querySelectorAll(".kc-tab").forEach(function (btn) {
            btn.onclick = function () { switchTab(btn.getAttribute("data-tab")); };
        });
        var mapSelAll = document.getElementById("kcMapSelectAll");
        if (mapSelAll) {
            mapSelAll.onchange = function () {
                if (mapSelAll.checked) state.contentPlans.forEach(function (p) { state.mapSelected.add(p.cluster_id); });
                else state.mapSelected.clear();
                renderContentMapTable();
            };
        }
        var briefClose = document.getElementById("kcBriefClose");
        if (briefClose) briefClose.onclick = closeBriefModal;
        var briefCancel = document.getElementById("kcBriefCancel");
        if (briefCancel) briefCancel.onclick = closeBriefModal;
        var briefSave = document.getElementById("kcBriefSave");
        if (briefSave) briefSave.onclick = saveBriefModal;
        var briefBd = document.getElementById("kcBriefBackdrop");
        if (briefBd) briefBd.onclick = closeBriefModal;
        var selAll = document.getElementById("kcSelectAll");
        if (selAll) {
            selAll.onchange = function () {
                if (selAll.checked) state.clusters.forEach(function (c) { state.selected.add(c.cluster_id); });
                else state.selected.clear();
                renderGrid();
            };
        }
    }

    function render(payload) {
        state.payload = payload || {};
        state.clusters = (payload && payload.clusters) || [];
        state.contentPlans = (payload && payload.content_plans) || [];
        state.selected.clear();
        state.mapSelected.clear();
        state.planEdits = {};
        if (!state.contentPlans.length) syncContentPlans();
        var panel = document.getElementById("panel");
        if (panel) panel.hidden = state.clusters.length === 0;
        var summary = payload.content_map_summary || {};
        if (!summary.cluster_count && state.clusters.length) {
            summary = {
                cluster_count: state.clusters.length,
                total_keywords: state.clusters.reduce(function (a, c) { return a + (c.total_keyword || 0); }, 0),
                total_volume: payload.meta && payload.meta.search_volume_sum,
                articles_suggested: state.contentPlans.length || state.clusters.length,
            };
        }
        renderSummary(summary);
        var chartData = state.clusters.slice().sort(function (a, b) {
            return (clusterTotalVol(b) || 0) - (clusterTotalVol(a) || 0);
        }).slice(0, 12).map(function (c) {
            return { label: c.main_keyword || c.topic, vol: clusterTotalVol(c) || 0 };
        });
        drawChart(chartData);
        renderGrid();
        renderContentMapTable();
        setLoading(false);
        switchTab(state.activeTab || "clusters");
        bindChrome();
    }

    global.KcSaaS = {
        render: render,
        fmtVol: fmtVol,
        fmtNum: fmtNum,
        switchTab: switchTab,
        showToast: showToast,
        setLoading: setLoading,
        friendlyStatus: friendlyStatus,
    };

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", bindChrome);
    } else {
        bindChrome();
    }
})(window);
