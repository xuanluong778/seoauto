/**
 * Schema SaaS UI — URL / Manual / Bulk / History
 */
(function () {
    "use strict";

    /** Single source of truth for the JSON-LD currently shown in the output panel. */
    var currentJsonLd = null;

    var state = {
        resultId: null,
        bulkJobId: null,
        pollTimer: null,
    };

    function el(id) {
        return document.getElementById(id);
    }

    function isNonEmptyObject(obj) {
        return !!obj && typeof obj === "object" && !Array.isArray(obj) && Object.keys(obj).length > 0;
    }

    /**
     * Normalize a schema node, schemas[], or document into valid JSON-LD.
     * Arrays become @graph (or a single node when length === 1).
     */
    function normalizeJsonLd(value) {
        if (value == null) return null;
        if (Array.isArray(value)) {
            var nodes = value.filter(function (n) {
                return isNonEmptyObject(n);
            });
            if (!nodes.length) return null;
            if (nodes.length === 1) {
                var one = Object.assign({}, nodes[0]);
                if (!one["@context"]) one["@context"] = "https://schema.org";
                return one;
            }
            return { "@context": "https://schema.org", "@graph": nodes };
        }
        if (typeof value === "string") {
            try {
                return normalizeJsonLd(JSON.parse(value));
            } catch (_) {
                return null;
            }
        }
        if (!isNonEmptyObject(value)) return null;
        // Empty @graph only — treat as missing so callers can fall back.
        if (Array.isArray(value["@graph"]) && value["@graph"].length === 0 && !value["@type"]) {
            return null;
        }
        return value;
    }

    /**
     * Extract JSON-LD from API payload.
     * Priority: primary_schema → schemas → json_ld / jsonld
     * When schemas[] has multiple nodes, use the full array (@graph) so
     * Copy / Validate cover every entity, not only the primary type.
     */
    function extractJsonLdFromResponse(data) {
        if (!data || typeof data !== "object") return null;
        var item = data.item && typeof data.item === "object" ? data.item : {};

        var primary = data.primary_schema || item.primary_schema;
        var schemas = data.schemas || item.schemas;
        var doc = data.json_ld || data.jsonld || item.json_ld || item.jsonld;

        if (Array.isArray(schemas) && schemas.length > 1) {
            var fromSchemasMulti = normalizeJsonLd(schemas);
            if (fromSchemasMulti) return fromSchemasMulti;
        }

        var fromPrimary = normalizeJsonLd(primary);
        if (fromPrimary) return fromPrimary;

        var fromSchemas = normalizeJsonLd(schemas);
        if (fromSchemas) return fromSchemas;

        return normalizeJsonLd(doc);
    }

    /** Read current JSON-LD from memory, or recover from the rendered <pre> output. */
    function getCurrentJsonLd() {
        if (currentJsonLd) return currentJsonLd;
        var code = el("outputCode");
        if (!code) return null;
        var text = (code.textContent || "").trim();
        if (!text || text.indexOf("//") === 0) return null;
        var parsed = normalizeJsonLd(text);
        if (parsed) currentJsonLd = parsed;
        return currentJsonLd;
    }

    function setCurrentJsonLd(value) {
        currentJsonLd = normalizeJsonLd(value);
        return currentJsonLd;
    }

    function getManualOutputFormat() {
        var r = document.querySelector('#cardManualInput input[name="mfOutputFormat"]:checked');
        return r && r.value === "script" ? "script" : "json";
    }

    function isManualTabActive() {
        var card = el("cardManualInput");
        return !!(card && !card.hidden);
    }

    /** Pure JSON-LD only — never inject anti-copy or unrelated scripts. */
    function formatJsonLdForDisplay(doc) {
        if (!doc) return "// Kết quả sẽ hiện ở đây";
        var json = JSON.stringify(doc, null, 2);
        if (isManualTabActive() && getManualOutputFormat() === "script") {
            return '<script type="application/ld+json">\n' + json + "\n</" + "script>";
        }
        return json;
    }

    function renderOutputCode(doc) {
        var code = el("outputCode");
        if (!code) return;
        code.textContent = formatJsonLdForDisplay(doc);
    }

    function requireCurrentJsonLd(msgNode, emptyMsg) {
        var doc = getCurrentJsonLd();
        if (!doc) {
            setMsg(msgNode || el("outputMsg"), emptyMsg || "Chưa có kết quả để kiểm tra.", false);
            return null;
        }
        return doc;
    }

    // Expose for smoke tests / debugging
    window.SchemaToolState = {
        getCurrentJsonLd: getCurrentJsonLd,
        extractJsonLdFromResponse: extractJsonLdFromResponse,
        normalizeJsonLd: normalizeJsonLd,
    };


    function getToken() {
        if (typeof window.DigiSeoGetAuthToken === "function") {
            return window.DigiSeoGetAuthToken() || "";
        }
        try {
            return (sessionStorage.getItem("seo_token") || "").trim();
        } catch (_) {
            return "";
        }
    }

    function authHeaders(json) {
        var h = {};
        if (json) h["Content-Type"] = "application/json";
        var t = getToken();
        if (t) h.Authorization = "Bearer " + t;
        return h;
    }

    function setMsg(node, text, ok) {
        if (!node) return;
        node.textContent = text || "";
        node.className = "schema-msg" + (text ? (ok ? " ok" : " err") : "");
    }

    function showInsufficient(detail) {
        var d = detail && typeof detail === "object" ? detail : {};
        var msg =
            d.message ||
            "Không đủ credit. Vui lòng nâng cấp gói hoặc mua thêm credit.";
        var url = d.upgrade_url || "/pricing";
        return msg + " → " + url;
    }

    async function api(path, opts) {
        opts = opts || {};
        var res = await fetch(path, {
            method: opts.method || "GET",
            headers: authHeaders(!!opts.body),
            credentials: "same-origin",
            body: opts.body ? JSON.stringify(opts.body) : undefined,
        });
        var data = null;
        try {
            data = await res.json();
        } catch (_) {
            data = null;
        }
        if (res.status === 401) {
            throw new Error("Bạn cần đăng nhập để dùng Schema Generator.");
        }
        if (res.status === 402) {
            var detail = (data && data.detail) || data || {};
            throw new Error(showInsufficient(detail));
        }
        // 422 may still include schemas / primary_schema — apply them in the UI.
        if (
            !res.ok &&
            res.status === 422 &&
            data &&
            (data.primary_schema ||
                (Array.isArray(data.schemas) && data.schemas.length) ||
                data.json_ld ||
                data.jsonld)
        ) {
            return data;
        }
        if (!res.ok) {
            var err =
                (data && data.detail && (data.detail.message || data.detail)) ||
                (data && data.message) ||
                "Request failed (" + res.status + ")";
            if (typeof err === "object") err = err.message || JSON.stringify(err);
            throw new Error(String(err));
        }
        return data;
    }

    function renderList(ul, items, empty) {
        if (!ul) return;
        ul.innerHTML = "";
        var arr = items || [];
        if (!arr.length) {
            ul.textContent = empty || "—";
            return;
        }
        arr.forEach(function (it) {
            var li = document.createElement("li");
            li.textContent = typeof it === "string" ? it : JSON.stringify(it);
            ul.appendChild(li);
        });
    }

    function renderPills(node, items, activeMap) {
        if (!node) return;
        node.innerHTML = "";
        var arr = items || [];
        if (!arr.length) {
            node.textContent = "—";
            return;
        }
        arr.forEach(function (it) {
            var span = document.createElement("span");
            span.className = "schema-pill" + (activeMap && activeMap[it] ? " on" : "");
            span.textContent = it;
            node.appendChild(span);
        });
    }

    function applyResult(data) {
        data = data || {};
        var extracted = extractJsonLdFromResponse(data);
        // Keep previous JSON-LD if this payload only updates validation scores.
        if (extracted) {
            setCurrentJsonLd(extracted);
        } else if (!getCurrentJsonLd()) {
            setCurrentJsonLd(null);
        }
        state.resultId =
            data.result_id != null
                ? data.result_id
                : data.item && data.item.id != null
                  ? data.item.id
                  : state.resultId;

        renderOutputCode(getCurrentJsonLd());

        var score = data.schema_score;
        if (data.item && data.item.schema_score != null) score = data.item.schema_score;
        if (data.validation && data.validation.schema_score != null && score == null) {
            score = data.validation.schema_score;
        }
        el("scoreValue").textContent = score != null ? String(score) : "—";

        var eligible = data.eligible_rich_results || (data.item && data.item.eligible_rich_results) || [];
        var errors = data.errors || (data.item && data.item.errors) || [];
        var warnings = data.warnings || (data.item && data.item.warnings) || [];
        var opps = data.opportunities || (data.item && data.item.opportunities) || [];
        var reason = data.type_reason || (data.item && data.item.type_reason) || "—";
        var signals = data.detected_signals || (data.item && data.item.detected_signals) || {};

        if (data.item && data.item.validation) {
            var v = data.item.validation;
            eligible = v.eligible_rich_results || eligible;
            errors = v.errors || errors;
            warnings = v.warnings || warnings;
            opps = v.opportunities || opps;
        }
        if (data.validation && typeof data.validation === "object") {
            var vr = data.validation;
            if (vr.errors && vr.errors.length) errors = vr.errors;
            if (vr.warnings && vr.warnings.length) warnings = vr.warnings;
            if (score == null && vr.schema_score != null) score = vr.schema_score;
        }
        if ((!eligible || !eligible.length) && Array.isArray(data.schemas)) {
            eligible = data.schemas
                .map(function (s) {
                    return s && s["@type"];
                })
                .filter(Boolean);
        }
        if (reason === "—" && data.primary_schema && data.primary_schema["@type"]) {
            reason = "Loại chính: " + data.primary_schema["@type"];
        }
        if (data.detected_types && data.detected_types.length) {
            signals = {};
            data.detected_types.forEach(function (t) {
                signals[t] = true;
            });
        }
        if (score == null && (errors.length || warnings.length)) {
            score = Math.max(0, 100 - errors.length * 12 - warnings.length * 4);
        }

        renderPills(el("valEligible"), eligible);
        renderList(el("valErrors"), errors, "Không có lỗi");
        renderList(el("valWarnings"), warnings, "Không có cảnh báo");
        renderList(el("valOpps"), opps, "—");
        el("valReason").textContent = reason;

        var sigKeys = Object.keys(signals).filter(function (k) {
            return !!signals[k];
        });
        renderPills(el("valSignals"), sigKeys.length ? sigKeys : ["(none)"], signals);
    }

    function switchTab(name) {
        document.querySelectorAll(".schema-tab").forEach(function (btn) {
            var on = btn.getAttribute("data-tab") === name;
            btn.classList.toggle("active", on);
            btn.setAttribute("aria-selected", on ? "true" : "false");
        });
        var ws = el("panelWorkspace");
        var bulk = el("panelBulk");
        var hist = el("panelHistory");
        var isWork = name === "url" || name === "manual";
        if (ws) ws.hidden = !isWork;
        if (bulk) bulk.hidden = name !== "bulk";
        if (hist) hist.hidden = name !== "history";
        if (el("cardUrlInput")) el("cardUrlInput").hidden = name !== "url";
        if (el("cardManualInput")) el("cardManualInput").hidden = name !== "manual";
        if (name === "history") loadHistory();
        if (name === "manual") scheduleManualPreview();
    }

    async function generateFromUrl() {
        var msg = el("urlMsg");
        setMsg(msg, "Đang tạo schema…", true);
        try {
            var url = (el("inputUrl").value || "").trim();
            var html = (el("inputHtml").value || "").trim();
            var body = {
                fetch_serp: !!(el("inputFetchSerp") && el("inputFetchSerp").checked),
            };
            if (url) body.url = url;
            if (html) {
                if (html.indexOf("<") >= 0) body.html = html;
                else body.text = html;
            }
            if (!body.url && !body.html && !body.text) {
                throw new Error("Nhập URL hoặc HTML/text.");
            }
            var data = await api("/schema-generator", { method: "POST", body: body });
            applyResult(data);
            if (!getCurrentJsonLd()) {
                throw new Error("API trả kết quả nhưng không có JSON-LD hợp lệ.");
            }
            setMsg(
                msg,
                "Đã tạo schema" +
                    (data.credit_charged ? " (−" + data.credit_charged + " credit)" : "") +
                    (data.result_id ? " · đã lưu #" + data.result_id : ""),
                true
            );
            refreshCreditPill();

        } catch (e) {
            setMsg(msg, e.message || String(e), false);
        }
    }

    /* —— Manual form (Tạo thủ công) — client-side only —— */

    function mfVal(id) {
        var node = el(id);
        return node ? String(node.value || "").trim() : "";
    }

    function mfLines(id) {
        return mfVal(id)
            .split(/\r?\n/)
            .map(function (s) {
                return s.trim();
            })
            .filter(Boolean);
    }

    /** SameAs: one URL per line, trim, drop blanks, keep only valid http(s) URLs. */
    function isValidHttpUrl(s) {
        if (!s) return false;
        try {
            var u = new URL(s);
            return u.protocol === "http:" || u.protocol === "https:";
        } catch (_) {
            return false;
        }
    }

    function mfSameAsUrls(id) {
        return mfLines(id).filter(isValidHttpUrl);
    }

    function mfPut(obj, key, value) {
        if (value === "" || value == null) return;
        obj[key] = value;
    }

    function isBareTypeOnly(doc) {
        if (!doc || typeof doc !== "object") return true;
        if (Array.isArray(doc["@graph"])) {
            if (!doc["@graph"].length) return true;
            return doc["@graph"].every(function (n) {
                return isBareTypeOnly(n);
            });
        }
        var keys = Object.keys(doc).filter(function (k) {
            return k !== "@context" && k !== "@type";
        });
        return keys.length === 0;
    }

    function mfPostalAddress(prefix) {
        var street = mfVal(prefix + "Street");
        var locality = mfVal(prefix + "Locality");
        var region = mfVal(prefix + "Region");
        var postal = mfVal(prefix + "Postal");
        var country = mfVal(prefix + "Country");
        if (!street && !locality && !region && !postal && !country) return null;
        var addr = { "@type": "PostalAddress" };
        mfPut(addr, "streetAddress", street);
        mfPut(addr, "addressLocality", locality);
        mfPut(addr, "addressRegion", region);
        mfPut(addr, "postalCode", postal);
        mfPut(addr, "addressCountry", country);
        return addr;
    }

    function mfLocalDatetime(id) {
        var v = mfVal(id);
        if (!v) return "";
        // datetime-local → ISO-ish
        if (v.length === 16) return v + ":00";
        return v;
    }

    function syncManualTypeBlocks() {
        var kind = (el("manualKind") && el("manualKind").value) || "Organization";
        document.querySelectorAll(".mf-type-block").forEach(function (block) {
            var types = (block.getAttribute("data-mf-type") || "").split(/\s+/);
            block.hidden = types.indexOf(kind) === -1;
        });
        if (kind === "FAQPage" && el("mfFaqRows") && !el("mfFaqRows").children.length) {
            addFaqRow();
        }
        if (kind === "BreadcrumbList" && el("mfCrumbRows") && !el("mfCrumbRows").children.length) {
            addCrumbRow();
            addCrumbRow();
        }
        scheduleManualPreview();
    }

    function addFaqRow(q, a) {
        var list = el("mfFaqRows");
        if (!list) return;
        var row = document.createElement("div");
        row.className = "mf-repeat-row mf-faq-row";
        row.innerHTML =
            '<label class="schema-lbl">Question</label>' +
            '<input type="text" class="schema-input mf-faq-q" placeholder="VD: Schema JSON-LD là gì?" />' +
            '<label class="schema-lbl">Answer</label>' +
            '<textarea class="schema-textarea mf-faq-a" rows="2" placeholder="VD: Là định dạng dữ liệu có cấu trúc giúp Google hiểu nội dung trang."></textarea>' +
            '<div class="mf-row-actions"><button type="button" class="schema-btn ghost mf-remove-row">Xoá</button></div>';
        if (q) row.querySelector(".mf-faq-q").value = q;
        if (a) row.querySelector(".mf-faq-a").value = a;
        row.querySelector(".mf-remove-row").addEventListener("click", function () {
            row.remove();
        });
        list.appendChild(row);
    }

    function addCrumbRow(name, url) {
        var list = el("mfCrumbRows");
        if (!list) return;
        var row = document.createElement("div");
        row.className = "mf-repeat-row mf-crumb-row";
        row.innerHTML =
            '<div><label class="schema-lbl">Name</label><input type="text" class="schema-input mf-crumb-name" placeholder="VD: Trang chủ / Sản phẩm" /></div>' +
            '<div><label class="schema-lbl">URL</label><input type="url" class="schema-input mf-crumb-url" placeholder="VD: https://thegioidigi.com/san-pham" /></div>' +
            '<div class="mf-row-actions"><button type="button" class="schema-btn ghost mf-remove-row">Xoá</button></div>';
        if (name) row.querySelector(".mf-crumb-name").value = name;
        if (url) row.querySelector(".mf-crumb-url").value = url;
        row.querySelector(".mf-remove-row").addEventListener("click", function () {
            row.remove();
        });
        list.appendChild(row);
    }

    function collectFaqPairs() {
        var pairs = [];
        document.querySelectorAll("#mfFaqRows .mf-faq-row").forEach(function (row) {
            var q = (row.querySelector(".mf-faq-q").value || "").trim();
            var a = (row.querySelector(".mf-faq-a").value || "").trim();
            if (q && a) pairs.push({ question: q, answer: a });
        });
        return pairs;
    }

    function collectCrumbs() {
        var items = [];
        document.querySelectorAll("#mfCrumbRows .mf-crumb-row").forEach(function (row) {
            var name = (row.querySelector(".mf-crumb-name").value || "").trim();
            var url = (row.querySelector(".mf-crumb-url").value || "").trim();
            if (name) items.push({ name: name, url: url });
        });
        return items;
    }

    function buildManualPackage() {
        var kind = (el("manualKind") && el("manualKind").value) || "Organization";
        var warnings = [];
        var opportunities = [];
        var nodes = [];
        var primary = null;
        var signals = { manual: true };

        function warnMissing(label, ok) {
            if (!ok) warnings.push("Thiếu field quan trọng: " + label);
        }

        if (kind === "Organization") {
            var orgName = mfVal("mfOrgName");
            var orgUrl = mfVal("mfOrgUrl");
            var origin = "";
            try {
                if (orgUrl) origin = new URL(orgUrl).origin;
            } catch (_) {
                origin = "";
            }
            var orgId = origin ? origin + "/#organization" : "";
            var websiteId = origin ? origin + "/#website" : "";

            var org = { "@type": "Organization" };
            if (orgId) org["@id"] = orgId;
            mfPut(org, "name", orgName);
            mfPut(org, "legalName", mfVal("mfOrgLegalName"));
            mfPut(org, "alternateName", mfVal("mfOrgAlternateName"));
            mfPut(org, "url", orgUrl);
            mfPut(org, "description", mfVal("mfOrgDesc"));
            mfPut(org, "logo", mfVal("mfOrgLogo"));
            mfPut(org, "foundingDate", mfVal("mfOrgFoundingDate"));
            mfPut(org, "email", mfVal("mfOrgEmail"));
            mfPut(org, "telephone", mfVal("mfOrgPhone"));

            var founderNames = mfLines("mfOrgFounders");
            if (founderNames.length === 1) {
                org.founder = { "@type": "Person", name: founderNames[0] };
            } else if (founderNames.length > 1) {
                org.founder = founderNames.map(function (n) {
                    return { "@type": "Person", name: n };
                });
            }

            var knowsAbout = mfLines("mfOrgKnowsAbout");
            if (knowsAbout.length) org.knowsAbout = knowsAbout;

            var areas = mfLines("mfOrgAreaServed");
            if (areas.length === 1) org.areaServed = areas[0];
            else if (areas.length > 1) org.areaServed = areas;

            var orgSame = mfSameAsUrls("mfOrgSameAs");
            if (orgSame.length) org.sameAs = orgSame;

            var orgAddr = mfPostalAddress("mfOrg");
            if (orgAddr) org.address = orgAddr;

            var cpPhone = mfVal("mfOrgContactPhone");
            var cpEmail = mfVal("mfOrgContactEmail");
            var cpType = mfVal("mfOrgContactType");
            var cpArea = mfVal("mfOrgContactArea");
            var cpLang = mfVal("mfOrgContactLang");
            if (cpPhone || cpEmail || cpType || cpArea || cpLang) {
                var cp = { "@type": "ContactPoint" };
                mfPut(cp, "contactType", cpType || "customer service");
                mfPut(cp, "telephone", cpPhone);
                mfPut(cp, "email", cpEmail);
                mfPut(cp, "areaServed", cpArea);
                mfPut(cp, "availableLanguage", cpLang);
                org.contactPoint = cp;
            }

            warnMissing("name", !!orgName);
            warnMissing("url", !!orgUrl);
            if (!org.logo) opportunities.push("Thêm logo để đủ rich result Organization.");
            if (!orgSame.length) opportunities.push("Thêm sameAs (social profiles) để tăng entity signals.");

            primary = org;
            nodes = [org];
            signals.organization = true;

            var includeWs = !!(el("mfOrgIncludeWebsite") && el("mfOrgIncludeWebsite").checked);
            if (includeWs && origin && orgId && websiteId) {
                var site = {
                    "@type": "WebSite",
                    "@id": websiteId,
                    url: origin,
                    publisher: { "@id": orgId },
                };
                var wsName = mfVal("mfOrgWsName") || orgName;
                mfPut(site, "name", wsName);
                var enableSearch = !!(el("mfOrgEnableSearch") && el("mfOrgEnableSearch").checked);
                var searchUrl = mfVal("mfOrgSearchUrl");
                if (enableSearch && searchUrl) {
                    site.potentialAction = {
                        "@type": "SearchAction",
                        target: searchUrl,
                        "query-input": "required name=search_term_string",
                    };
                } else if (enableSearch && !searchUrl) {
                    warnings.push("Đã bật SearchAction nhưng chưa nhập Search URL pattern.");
                }
                nodes.push(site);
                signals.website = true;
            } else if (includeWs && !origin) {
                warnings.push("Cần url hợp lệ (https://domain) để tạo WebSite @id theo domain/#website.");
            }
        } else if (kind === "LocalBusiness") {
            var lb = { "@type": "LocalBusiness" };
            var lbName = mfVal("mfLbName");
            var lbUrl = mfVal("mfLbUrl");
            mfPut(lb, "name", lbName);
            mfPut(lb, "url", lbUrl);
            mfPut(lb, "description", mfVal("mfLbDesc"));
            mfPut(lb, "image", mfVal("mfLbImage"));
            mfPut(lb, "telephone", mfVal("mfLbPhone"));
            mfPut(lb, "email", mfVal("mfLbEmail"));
            mfPut(lb, "priceRange", mfVal("mfLbPriceRange"));
            var lbAddr = mfPostalAddress("mfLb");
            if (lbAddr) lb.address = lbAddr;
            var hours = mfLines("mfLbHours");
            if (hours.length === 1) lb.openingHours = hours[0];
            else if (hours.length > 1) lb.openingHours = hours;
            var lbSame = mfSameAsUrls("mfLbSameAs");
            if (lbSame.length) lb.sameAs = lbSame;
            var lat = mfVal("mfLbLat");
            var lng = mfVal("mfLbLng");
            if (lat && lng) {
                lb.geo = { "@type": "GeoCoordinates", latitude: lat, longitude: lng };
            }
            warnMissing("Tên doanh nghiệp", !!lbName);
            warnMissing("Địa chỉ (street hoặc locality)", !!(lbAddr && (lbAddr.streetAddress || lbAddr.addressLocality)));
            if (!lb.telephone) opportunities.push("Thêm số điện thoại cho LocalBusiness.");
            primary = lb;
            nodes = [lb];
        } else if (kind === "Article" || kind === "BlogPosting") {
            var art = { "@type": kind };
            var headline = mfVal("mfArtHeadline");
            var artUrl = mfVal("mfArtUrl");
            mfPut(art, "headline", headline);
            mfPut(art, "mainEntityOfPage", artUrl || undefined);
            if (artUrl) art.url = artUrl;
            mfPut(art, "description", mfVal("mfArtDesc"));
            var artImg = mfVal("mfArtImage");
            if (artImg) art.image = [artImg];
            var author = mfVal("mfArtAuthor");
            if (author) art.author = { "@type": "Person", name: author };
            var pub = mfVal("mfArtPublisher");
            var pubLogo = mfVal("mfArtPubLogo");
            if (pub) {
                art.publisher = { "@type": "Organization", name: pub };
                if (pubLogo) art.publisher.logo = { "@type": "ImageObject", url: pubLogo };
            }
            mfPut(art, "datePublished", mfLocalDatetime("mfArtPublished"));
            mfPut(art, "dateModified", mfLocalDatetime("mfArtModified"));
            mfPut(art, "keywords", mfVal("mfArtKeywords"));
            warnMissing("Headline", !!headline);
            if (!author) warnings.push("Thiếu field quan trọng: Author name");
            if (!art.datePublished) warnings.push("Thiếu field quan trọng: Date published");
            if (!artImg) opportunities.push("Thêm Image URL để đủ Article rich results.");
            primary = art;
            nodes = [art];
        } else if (kind === "Product") {
            var prod = { "@type": "Product" };
            var pName = mfVal("mfProdName");
            var pUrl = mfVal("mfProdUrl");
            mfPut(prod, "name", pName);
            mfPut(prod, "url", pUrl);
            mfPut(prod, "description", mfVal("mfProdDesc"));
            var pImg = mfVal("mfProdImage");
            if (pImg) prod.image = [pImg];
            var brand = mfVal("mfProdBrand");
            if (brand) prod.brand = { "@type": "Brand", name: brand };
            mfPut(prod, "sku", mfVal("mfProdSku"));
            var price = mfVal("mfProdPrice");
            var currency = mfVal("mfProdCurrency");
            var avail = mfVal("mfProdAvailability");
            var cond = mfVal("mfProdCondition");
            if (price || currency || avail || cond || pUrl) {
                var offer = { "@type": "Offer" };
                mfPut(offer, "url", pUrl);
                if (price) offer.price = price;
                mfPut(offer, "priceCurrency", currency);
                mfPut(offer, "availability", avail);
                mfPut(offer, "itemCondition", cond);
                prod.offers = offer;
            }
            var ratingVal = mfVal("mfProdRating");
            var ratingCount = mfVal("mfProdRatingCount");
            if (ratingVal) {
                var agg = { "@type": "AggregateRating", ratingValue: ratingVal, bestRating: "5" };
                if (ratingCount) agg.ratingCount = ratingCount;
                prod.aggregateRating = agg;
            }
            var reviewBody = mfVal("mfProdReviewBody");
            var reviewAuthor = mfVal("mfProdReviewAuthor");
            if (reviewBody) {
                var review = { "@type": "Review", reviewBody: reviewBody };
                if (reviewAuthor) review.author = { "@type": "Person", name: reviewAuthor };
                prod.review = [review];
            }
            warnMissing("Product name", !!pName);
            if (!price) warnings.push("Thiếu field quan trọng: Price (Merchant listings cần giá)");
            if (!pImg) opportunities.push("Thêm Image URL cho Product rich results.");
            primary = prod;
            nodes = [prod];
        } else if (kind === "WebSite") {
            var wsUrl = mfVal("mfWsUrl");
            var wsName = mfVal("mfWsName");
            var site = { "@type": "WebSite" };
            mfPut(site, "name", wsName);
            mfPut(site, "url", wsUrl);
            mfPut(site, "description", mfVal("mfWsDesc"));
            var search = mfVal("mfWsSearch");
            if (search) {
                site.potentialAction = {
                    "@type": "SearchAction",
                    target: search,
                    "query-input": "required name=search_term_string",
                };
            }
            var orgNameWs = mfVal("mfWsOrg");
            nodes = [site];
            if (orgNameWs) {
                var orgNode = {
                    "@type": "Organization",
                    name: orgNameWs,
                };
                if (wsUrl) orgNode.url = wsUrl;
                site.publisher = { "@type": "Organization", name: orgNameWs };
                nodes.push(orgNode);
            }
            warnMissing("Website name", !!wsName);
            warnMissing("URL", !!wsUrl);
            primary = site;
        } else if (kind === "Person") {
            var person = { "@type": "Person" };
            var perName = mfVal("mfPerName");
            mfPut(person, "name", perName);
            mfPut(person, "url", mfVal("mfPerUrl"));
            mfPut(person, "image", mfVal("mfPerImage"));
            mfPut(person, "jobTitle", mfVal("mfPerJob"));
            mfPut(person, "description", mfVal("mfPerDesc"));
            var worksFor = mfVal("mfPerWorksFor");
            if (worksFor) person.worksFor = { "@type": "Organization", name: worksFor };
            var perSame = mfSameAsUrls("mfPerSameAs");
            if (perSame.length) person.sameAs = perSame;
            warnMissing("Name", !!perName);
            primary = person;
            nodes = [person];
        } else if (kind === "Service") {
            var svc = { "@type": "Service" };
            var svcName = mfVal("mfSvcName");
            mfPut(svc, "name", svcName);
            mfPut(svc, "url", mfVal("mfSvcUrl"));
            mfPut(svc, "description", mfVal("mfSvcDesc"));
            mfPut(svc, "serviceType", mfVal("mfSvcType"));
            mfPut(svc, "image", mfVal("mfSvcImage"));
            mfPut(svc, "areaServed", mfVal("mfSvcArea"));
            var provider = mfVal("mfSvcProvider");
            if (provider) svc.provider = { "@type": "Organization", name: provider };
            mfPut(svc, "priceRange", mfVal("mfSvcPriceRange"));
            warnMissing("Service name", !!svcName);
            if (!provider) opportunities.push("Thêm Provider name để liên kết Organization.");
            primary = svc;
            nodes = [svc];
        } else if (kind === "FAQPage") {
            var pairs = collectFaqPairs();
            if (!pairs.length) {
                warnings.push("Cần ít nhất 1 cặp Question/Answer thật để tạo FAQPage.");
            }
            var faq = { "@type": "FAQPage", mainEntity: [] };
            pairs.forEach(function (p) {
                faq.mainEntity.push({
                    "@type": "Question",
                    name: p.question,
                    acceptedAnswer: { "@type": "Answer", text: p.answer },
                });
            });
            primary = faq;
            nodes = pairs.length ? [faq] : [];
        } else if (kind === "BreadcrumbList") {
            var crumbs = collectCrumbs();
            if (!crumbs.length) {
                warnings.push("Cần ít nhất 1 breadcrumb item (name).");
            }
            var crumb = { "@type": "BreadcrumbList", itemListElement: [] };
            crumbs.forEach(function (c, i) {
                var li = { "@type": "ListItem", position: i + 1, name: c.name };
                if (c.url) li.item = c.url;
                crumb.itemListElement.push(li);
            });
            primary = crumb;
            nodes = crumbs.length ? [crumb] : [];
        } else {
            warnings.push("Loại schema không hỗ trợ: " + kind);
        }

        // Strip undefined keys from shallow nodes
        nodes = nodes.map(function (n) {
            var clean = {};
            Object.keys(n).forEach(function (k) {
                if (n[k] !== undefined && n[k] !== "") clean[k] = n[k];
            });
            return clean;
        });

        var jsonLd;
        if (nodes.length > 1) {
            jsonLd = { "@context": "https://schema.org", "@graph": nodes };
        } else if (nodes.length === 1) {
            jsonLd = Object.assign({ "@context": "https://schema.org" }, nodes[0]);
            primary = jsonLd;
        } else {
            jsonLd = null;
            primary = null;
        }

        var score = 40;
        if (primary) score += 25;
        if (warnings.length === 0) score += 20;
        else score -= Math.min(20, warnings.length * 5);
        if (opportunities.length === 0) score += 10;
        if (signals.website) score += 5;
        score = Math.max(0, Math.min(100, score));

        signals[String(kind).toLowerCase()] = true;

        return {
            kind: kind,
            primary: primary,
            nodes: nodes,
            jsonLd: jsonLd,
            warnings: warnings,
            opportunities: opportunities,
            score: score,
            signals: signals,
        };
    }

    var manualPreviewTimer = null;

    function renderManualEmptyPanel(kind) {
        setCurrentJsonLd(null);
        renderOutputCode(null);
        if (el("scoreValue")) el("scoreValue").textContent = "—";
        renderPills(el("valEligible"), []);
        renderList(el("valErrors"), [], "—");
        renderList(el("valWarnings"), [], "—");
        renderList(el("valOpps"), [], "—");
        if (el("valReason")) el("valReason").textContent = "Tạo thủ công — " + (kind || "Schema");
        var sig = { manual: true };
        if (kind) sig[kind] = true;
        renderPills(el("valSignals"), kind ? ["manual", kind] : ["manual"], sig);
    }

    function applyManualLivePreview() {
        var card = el("cardManualInput");
        if (!card || card.hidden) return;

        var pack;
        try {
            pack = buildManualPackage();
        } catch (e) {
            setMsg(el("manualMsg"), e.message || String(e), false);
            return;
        }

        state.resultId = null;

        if (!pack.jsonLd || isBareTypeOnly(pack.jsonLd)) {
            renderManualEmptyPanel(pack.kind);
            return;
        }

        setCurrentJsonLd(pack.jsonLd);
        applyResult({
            primary_schema: pack.primary,
            schemas: pack.nodes,
            json_ld: pack.jsonLd,
            schema_score: pack.score,
            eligible_rich_results: [],
            errors: [],
            warnings: pack.warnings,
            opportunities: pack.opportunities,
            type_reason: "Tạo thủ công — " + pack.kind,
            detected_signals: pack.signals,
        });
    }

    function scheduleManualPreview() {
        if (manualPreviewTimer) clearTimeout(manualPreviewTimer);
        manualPreviewTimer = setTimeout(function () {
            manualPreviewTimer = null;
            applyManualLivePreview();
        }, 250);
    }

    function manualBuild() {
        var msg = el("manualMsg");
        try {
            applyManualLivePreview();
            var doc = getCurrentJsonLd();
            if (!doc) {
                setMsg(msg, "Nhập ít nhất một thông tin để tạo mã.", false);
                return;
            }
            setMsg(msg, "Đã tạo mã thành công — miễn phí.", true);
        } catch (e) {
            setMsg(msg, e.message || String(e), false);
        }
    }

    function initManualForm() {
        var card = el("cardManualInput");
        if (!card || !el("manualKind")) return;

        el("manualKind").addEventListener("change", syncManualTypeBlocks);

        // Live preview: any field input/change inside manual card
        card.addEventListener("input", scheduleManualPreview);
        card.addEventListener("change", scheduleManualPreview);

        el("mfFaqAdd") &&
            el("mfFaqAdd").addEventListener("click", function () {
                addFaqRow();
                scheduleManualPreview();
            });
        el("mfCrumbAdd") &&
            el("mfCrumbAdd").addEventListener("click", function () {
                addCrumbRow();
                scheduleManualPreview();
            });

        // FAQ / breadcrumb remove buttons (delegated)
        card.addEventListener("click", function (ev) {
            var t = ev.target;
            if (t && t.classList && t.classList.contains("mf-remove-row")) {
                scheduleManualPreview();
            }
        });

        syncManualTypeBlocks();
    }

    async function copyOutput() {
        var doc = requireCurrentJsonLd(el("outputMsg"), "Chưa có kết quả để sao chép.");
        if (!doc) return;
        renderOutputCode(doc);
        var text = formatJsonLdForDisplay(doc);
        try {
            await navigator.clipboard.writeText(text);
            var asScript = isManualTabActive() && getManualOutputFormat() === "script";
            setMsg(el("outputMsg"), asScript ? "Đã sao chép mã gắn website." : "Đã sao chép kết quả.", true);
        } catch (_) {
            setMsg(el("outputMsg"), "Không sao chép được — hãy thử chọn và copy thủ công.", false);
        }
    }

    function downloadJson() {
        var doc = requireCurrentJsonLd(el("outputMsg"), "Chưa có kết quả để tải xuống.");
        if (!doc) return;
        renderOutputCode(doc);
        var asScript = isManualTabActive() && getManualOutputFormat() === "script";
        var text = formatJsonLdForDisplay(doc);
        var blob = new Blob([text], {
            type: asScript ? "text/html;charset=utf-8" : "application/json",
        });
        var a = document.createElement("a");
        a.href = URL.createObjectURL(blob);
        a.download = "schema-" + (state.resultId || "export") + (asScript ? ".html" : ".json");
        a.click();
        URL.revokeObjectURL(a.href);
        setMsg(el("outputMsg"), asScript ? "Đã tải mã gắn website." : "Đã tải kết quả.", true);
    }

    async function revalidate() {
        var doc = requireCurrentJsonLd(el("outputMsg"), "Chưa có kết quả để kiểm tra.");
        if (!doc) return;
        renderOutputCode(doc);
        try {
            var data = await api("/api/schema/validate", {
                method: "POST",
                body: { json_ld: doc },
            });
            // Keep the same JSON-LD; only refresh validation panel fields.
            applyResult(
                Object.assign({}, data, {
                    primary_schema: doc["@type"] ? doc : undefined,
                    schemas: doc["@graph"] || (doc["@type"] ? [doc] : undefined),
                    json_ld: doc,
                    result_id: state.resultId,
                    type_reason: (el("valReason") && el("valReason").textContent) || "—",
                    detected_signals: Object.assign({}, data.detected_signals || {}, { revalidated: true }),
                })
            );
            setMsg(el("outputMsg"), "Đã kiểm tra lại.", true);
        } catch (e) {
            setMsg(el("outputMsg"), e.message || String(e), false);
        }
    }

    async function saveProject() {
        var doc = requireCurrentJsonLd(el("outputMsg"), "Chưa có kết quả để lưu.");
        if (!doc) return;
        try {
            var data = await api("/api/schema/save", {
                method: "POST",
                body: {
                    json_ld: doc,
                    url: (el("manualUrl") && el("manualUrl").value) || (el("inputUrl") && el("inputUrl").value) || null,
                },
            });
            if (data.item) {
                state.resultId = data.item.id;
                applyResult(data);
            }
            setMsg(el("outputMsg"), "Đã lưu vào lịch sử.", true);
        } catch (e) {
            setMsg(el("outputMsg"), e.message || String(e), false);
        }
    }

    function buildHeadSnippet(doc) {
        return (
            '<script type="application/ld+json">\n' +
            JSON.stringify(doc, null, 2) +
            "\n</script>"
        );
    }

    async function openDeploy() {
        var doc = requireCurrentJsonLd(el("outputMsg"), "Chưa có kết quả để đưa lên WordPress.");
        if (!doc) return;
        var modal = el("deployModal");
        modal.hidden = false;
        el("deploySnippet").value = buildHeadSnippet(doc);
        setMsg(el("deployMsg"), "", true);
        try {
            var sites = await api("/api/schema/sites");
            var sel = el("deploySite");
            sel.innerHTML = '<option value="">— Chọn site —</option>';
            (sites.sites || []).forEach(function (s) {
                var opt = document.createElement("option");
                opt.value = s.id;
                opt.textContent = (s.name || s.url || s.id) + "";
                sel.appendChild(opt);
            });
        } catch (_) {
            var sel2 = el("deploySite");
            if (sel2) {
                sel2.innerHTML = '<option value="">— WordPress chưa kết nối —</option>';
            }
        }
    }

    async function deployWp() {
        try {
            var doc = getCurrentJsonLd();
            if (!doc) {
                setMsg(el("deployMsg"), "Chưa có kết quả để đưa lên WordPress.", false);
                return;
            }
            var data = await api("/api/schema/deploy", {
                method: "POST",
                body: {
                    method: "wordpress",
                    result_id: state.resultId,
                    json_ld: doc,
                    site_id: el("deploySite").value,
                    wp_post_id: el("deployPostId").value,
                },
            });
            setMsg(el("deployMsg"), data.message || "Deploy thành công.", true);
        } catch (e) {
            setMsg(el("deployMsg"), e.message || String(e), false);
        }
    }

    async function startBulk() {
        var msg = el("bulkMsg");
        setMsg(msg, "Đang khởi tạo bulk…", true);
        try {
            var text = el("bulkUrls").value || "";
            var data = await api("/api/schema/bulk/start", {
                method: "POST",
                body: { urls: text, fetch_serp: false },
            });
            state.bulkJobId = data.job_id;
            el("bulkProgressWrap").hidden = false;
            el("bulkExportWrap").hidden = false;
            el("btnExportCsv").href = "/api/schema/bulk/" + data.job_id + "/export.csv";
            el("btnExportXlsx").href = "/api/schema/bulk/" + data.job_id + "/export.xlsx";
            setMsg(msg, "Job #" + data.job_id + " đã chạy.", true);
            pollBulk();
        } catch (e) {
            setMsg(msg, e.message || String(e), false);
        }
    }

    async function pollBulk() {
        if (!state.bulkJobId) return;
        if (state.pollTimer) clearTimeout(state.pollTimer);
        try {
            var data = await api("/api/schema/bulk/" + state.bulkJobId);
            el("bulkProgressBar").style.width = (data.progress || 0) + "%";
            el("bulkProgressText").textContent =
                (data.progress || 0) + "% — " + (data.message || data.status || "");
            var tbody = el("bulkTableBody");
            tbody.innerHTML = "";
            (data.items || []).forEach(function (row) {
                var tr = document.createElement("tr");
                tr.innerHTML =
                    "<td>" +
                    row.stt +
                    "</td><td>" +
                    escapeHtml(row.url || "") +
                    "</td><td>" +
                    escapeHtml(row.primary_type || "—") +
                    "</td><td>" +
                    row.schema_score +
                    "</td><td>" +
                    row.errors +
                    "</td><td>" +
                    row.warnings +
                    "</td><td>" +
                    escapeHtml(row.status || "") +
                    '</td><td><button type="button" class="schema-btn ghost" data-view="' +
                    row.id +
                    '">View</button></td>';
                tbody.appendChild(tr);
            });
            tbody.querySelectorAll("[data-view]").forEach(function (btn) {
                btn.addEventListener("click", function () {
                    viewHistoryItem(btn.getAttribute("data-view"));
                });
            });
            if (data.status === "running" || data.status === "queued") {
                state.pollTimer = setTimeout(pollBulk, 1200);
            } else {
                refreshCreditPill();
            }
        } catch (e) {
            setMsg(el("bulkMsg"), e.message || String(e), false);
        }
    }

    function escapeHtml(s) {
        return String(s)
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;");
    }

    async function loadHistory() {
        var msg = el("historyMsg");
        try {
            var data = await api("/api/schema/history?limit=50");
            var tbody = el("historyTableBody");
            tbody.innerHTML = "";
            (data.items || []).forEach(function (row) {
                var tr = document.createElement("tr");
                tr.innerHTML =
                    "<td>" +
                    escapeHtml((row.created_at || "").replace("T", " ").slice(0, 19)) +
                    "</td><td>" +
                    escapeHtml(row.url || row.domain || "—") +
                    "</td><td>" +
                    escapeHtml(row.primary_type || "—") +
                    "</td><td>" +
                    row.schema_score +
                    "</td><td>" +
                    escapeHtml(row.source || "") +
                    '</td><td><button type="button" class="schema-btn ghost" data-view="' +
                    row.id +
                    '">View</button> <button type="button" class="schema-btn danger" data-del="' +
                    row.id +
                    '">Xoá</button></td>';
                tbody.appendChild(tr);
            });
            tbody.querySelectorAll("[data-view]").forEach(function (btn) {
                btn.addEventListener("click", function () {
                    viewHistoryItem(btn.getAttribute("data-view"));
                });
            });
            tbody.querySelectorAll("[data-del]").forEach(function (btn) {
                btn.addEventListener("click", function () {
                    deleteHistoryItem(btn.getAttribute("data-del"));
                });
            });
            setMsg(msg, (data.total || 0) + " mục", true);
        } catch (e) {
            setMsg(msg, e.message || String(e), false);
        }
    }

    async function viewHistoryItem(id) {
        try {
            var data = await api("/api/schema/history/" + id);
            switchTab("url");
            applyResult(data);
            setMsg(el("outputMsg"), "Đã tải lịch sử #" + id, true);
        } catch (e) {
            setMsg(el("historyMsg"), e.message || String(e), false);
        }
    }

    async function deleteHistoryItem(id) {
        if (!confirm("Xoá mục lịch sử #" + id + "?")) return;
        try {
            await api("/api/schema/history/" + id, { method: "DELETE" });
            loadHistory();
        } catch (e) {
            setMsg(el("historyMsg"), e.message || String(e), false);
        }
    }

    async function refreshCreditPill() {
        var pill = el("schemaCreditPill");
        if (!pill) return;
        pill.textContent = "Form thủ công: miễn phí";
        var hint = el("urlCreditHint");
        if (hint) {
            hint.textContent = "Tạo từ URL/HTML dùng engine phân tích trang — form thủ công không mất phí.";
        }
    }

    function bind() {
        document.querySelectorAll(".schema-tab").forEach(function (btn) {
            btn.addEventListener("click", function () {
                switchTab(btn.getAttribute("data-tab"));
            });
        });
        el("btnGenerateUrl") && el("btnGenerateUrl").addEventListener("click", generateFromUrl);
        el("btnManualBuild") && el("btnManualBuild").addEventListener("click", manualBuild);
        initManualForm();

        el("btnCopy") && el("btnCopy").addEventListener("click", copyOutput);
        el("btnDownload") && el("btnDownload").addEventListener("click", downloadJson);
        el("btnRevalidate") && el("btnRevalidate").addEventListener("click", revalidate);
        el("btnSaveProject") && el("btnSaveProject").addEventListener("click", saveProject);
        el("btnDeployWp") && el("btnDeployWp").addEventListener("click", openDeploy);
        el("btnDeployClose") &&
            el("btnDeployClose").addEventListener("click", function () {
                el("deployModal").hidden = true;
            });
        el("btnCopySnippet") &&
            el("btnCopySnippet").addEventListener("click", async function () {
                try {
                    await navigator.clipboard.writeText(el("deploySnippet").value || "");
                    setMsg(el("deployMsg"), "Đã copy mã head.", true);
                } catch (_) {
                    setMsg(el("deployMsg"), "Copy thất bại.", false);
                }
            });
        el("btnDeployWpConfirm") && el("btnDeployWpConfirm").addEventListener("click", deployWp);
        el("btnBulkStart") && el("btnBulkStart").addEventListener("click", startBulk);
        el("btnHistoryRefresh") && el("btnHistoryRefresh").addEventListener("click", loadHistory);

        // Auth headers for export links
        ["btnExportCsv", "btnExportXlsx"].forEach(function (id) {
            var a = el(id);
            if (!a) return;
            a.addEventListener("click", function (ev) {
                var t = getToken();
                if (!t) return;
                ev.preventDefault();
                fetch(a.href, { headers: authHeaders(false), credentials: "same-origin" })
                    .then(function (r) {
                        return r.blob().then(function (b) {
                            return { blob: b, ok: r.ok };
                        });
                    })
                    .then(function (x) {
                        if (!x.ok) throw new Error("Export failed");
                        var url = URL.createObjectURL(x.blob);
                        var link = document.createElement("a");
                        link.href = url;
                        link.download = a.id.indexOf("Xlsx") >= 0 ? "schema-bulk.xlsx" : "schema-bulk.csv";
                        link.click();
                        URL.revokeObjectURL(url);
                    })
                    .catch(function (e) {
                        setMsg(el("bulkMsg"), e.message || String(e), false);
                    });
            });
        });
    }

    function boot() {
        bind();
        switchTab("url");
        refreshCreditPill();
        // highlight nav
        try {
            document.querySelectorAll('a[href="/schema"]').forEach(function (a) {
                a.classList.add("active");
            });
        } catch (_) {}
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", boot);
    } else {
        boot();
    }
})();
