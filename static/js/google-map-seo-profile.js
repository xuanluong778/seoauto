/**
 * Google Map SEO — Tối ưu hồ sơ GBP bằng AI
 */
(function () {
    "use strict";

    var API = "/api/google-map-seo";

    var SECTIONS = [
        { id: "business_description", label: "Mô tả doanh nghiệp", apply: true },
        { id: "main_services", label: "Dịch vụ chính", apply: false },
        { id: "service_description", label: "Mô tả từng dịch vụ", apply: false },
        { id: "faq", label: "FAQ", apply: false },
        { id: "local_intro", label: "Giới thiệu địa phương", apply: true },
    ];

    var TONES = [
        { id: "professional", label: "Chuyên nghiệp" },
        { id: "friendly", label: "Thân thiện" },
        { id: "concise", label: "Ngắn gọn" },
        { id: "enthusiastic", label: "Nhiệt tình" },
    ];

    var profileState = {
        section: "business_description",
        outputs: {},
        warnings: {},
        loading: false,
        canApply: false,
    };

    function lsKey(locId, type) {
        return "gms_profile_" + locId + "_" + type;
    }

    function readLsDraft(locId, type) {
        try {
            var raw = localStorage.getItem(lsKey(locId, type));
            return raw ? JSON.parse(raw) : null;
        } catch (_e) {
            return null;
        }
    }

    function writeLsDraft(locId, type, data) {
        try {
            localStorage.setItem(lsKey(locId, type), JSON.stringify(data));
        } catch (_e) {}
    }

    function formatFaqDisplay(content) {
        try {
            var arr = JSON.parse(content);
            if (!Array.isArray(arr)) return content;
            return arr.map(function (item) {
                var q = item && item.q ? item.q : item.question;
                var a = item && item.a ? item.a : item.answer;
                return "H: " + q + "\nĐ: " + a;
            }).join("\n\n");
        } catch (_e) {
            return content;
        }
    }

    function prefillFromLocation(loc) {
        if (!loc) return {};
        var website = "";
        if (loc.website_uri) website = loc.website_uri;
        else if (loc.gbp && loc.gbp.website && loc.gbp.website.url) website = loc.gbp.website.url;
        return {
            business_name: loc.name || "",
            industry: loc.category || "",
            locality: loc.address || loc.locality || "",
            website: website,
            main_services: "",
            service_name: "",
            tone: "professional",
        };
    }

    function readForm(host) {
        function v(id) {
            var el = host.querySelector("#" + id);
            return el ? String(el.value || "").trim() : "";
        }
        return {
            business_name: v("gmsProfName"),
            industry: v("gmsProfIndustry"),
            locality: v("gmsProfLocality"),
            website: v("gmsProfWebsite"),
            main_services: v("gmsProfServices"),
            service_name: v("gmsProfServiceName"),
            tone: v("gmsProfTone") || "professional",
        };
    }

    function fillForm(host, data) {
        if (!data) return;
        var map = {
            gmsProfName: data.business_name,
            gmsProfIndustry: data.industry,
            gmsProfLocality: data.locality,
            gmsProfWebsite: data.website,
            gmsProfServices: data.main_services,
            gmsProfServiceName: data.service_name,
            gmsProfTone: data.tone || "professional",
        };
        Object.keys(map).forEach(function (id) {
            var el = host.querySelector("#" + id);
            if (el && map[id] != null) el.value = map[id];
        });
    }

    function renderHtml(ctx) {
        var loc = ctx.location;
        var locId = loc ? loc.id : "default";
        var section = profileState.section;
        var secMeta = SECTIONS.find(function (s) { return s.id === section; }) || SECTIONS[0];
        var output = profileState.outputs[section] || "";
        var warn = profileState.warnings[section] || [];
        var displayOut = section === "faq" && output ? formatFaqDisplay(output) : output;
        var applyHint = profileState.canApply && secMeta.apply
            ? '<span class="gms-badge gms-badge--ok">Có thể áp dụng lên GBP</span>'
            : '<span class="gms-muted">Sao chép / lưu nháp — áp dụng GBP chỉ cho mô tả & giới thiệu địa phương khi đã kết nối</span>';

        return (
            '<div class="gms-profile">' +
            '<div class="gms-profile__grid">' +
            '<div class="gms-card gms-profile__form">' +
            '<h2 class="gms-card-title">Thông tin doanh nghiệp</h2>' +
            '<p class="gms-hint">AI chỉ viết dựa trên dữ liệu bạn nhập hoặc đồng bộ từ GBP — không bịa thông tin.</p>' +
            '<label class="gms-field-label" for="gmsProfName">Tên doanh nghiệp</label>' +
            '<input type="text" class="gms-input" id="gmsProfName" maxlength="200" />' +
            '<label class="gms-field-label" for="gmsProfIndustry">Ngành nghề</label>' +
            '<input type="text" class="gms-input" id="gmsProfIndustry" maxlength="120" />' +
            '<label class="gms-field-label" for="gmsProfLocality">Tỉnh / thành / quận</label>' +
            '<input type="text" class="gms-input" id="gmsProfLocality" maxlength="200" />' +
            '<label class="gms-field-label" for="gmsProfWebsite">Website</label>' +
            '<input type="url" class="gms-input" id="gmsProfWebsite" maxlength="300" placeholder="https://" />' +
            '<label class="gms-field-label" for="gmsProfServices">Dịch vụ chính</label>' +
            '<textarea class="gms-textarea" id="gmsProfServices" rows="3" maxlength="1500" placeholder="Mỗi dòng một dịch vụ"></textarea>' +
            '<label class="gms-field-label" for="gmsProfServiceName">Tên dịch vụ (cho mô tả chi tiết)</label>' +
            '<input type="text" class="gms-input" id="gmsProfServiceName" maxlength="120" />' +
            '<label class="gms-field-label" for="gmsProfTone">Giọng văn</label>' +
            '<select class="gms-select gms-profile__tone" id="gmsProfTone">' +
            TONES.map(function (t) {
                return '<option value="' + t.id + '">' + t.label + "</option>";
            }).join("") +
            "</select></div>" +
            '<div class="gms-card gms-profile__out">' +
            '<div class="gms-profile__tabs" role="tablist">' +
            SECTIONS.map(function (s) {
                var on = s.id === section;
                return '<button type="button" class="gms-profile-tab' + (on ? " active" : "") + '" data-gms-prof-tab="' +
                    s.id + '" role="tab" aria-selected="' + (on ? "true" : "false") + '">' + s.label + "</button>";
            }).join("") +
            "</div>" +
            '<div class="gms-profile__actions">' +
            '<button type="button" class="gms-btn gms-btn--primary" id="gmsProfBtnAi" ' +
            (profileState.loading ? "disabled" : "") + ">Tạo bằng AI</button>" +
            '<button type="button" class="gms-btn gms-btn--secondary" id="gmsProfBtnCopy" ' +
            (!output ? "disabled" : "") + ">Sao chép</button>" +
            '<button type="button" class="gms-btn gms-btn--secondary" id="gmsProfBtnDraft" ' +
            (!output ? "disabled" : "") + ">Lưu nháp</button>" +
            '<button type="button" class="gms-btn gms-btn--secondary" id="gmsProfBtnApply" ' +
            (!output || !profileState.canApply || !secMeta.apply ? "disabled" : "") + ">Áp dụng vào hồ sơ</button>" +
            "</div>" +
            '<p class="gms-profile__apply-hint">' + applyHint + "</p>" +
            (warn.length
                ? '<ul class="gms-profile-warn">' + warn.map(function (w) {
                    return "<li>" + ctx.esc(w) + "</li>";
                }).join("") + "</ul>"
                : "") +
            '<label class="gms-field-label" for="gmsProfOutput">Kết quả AI</label>' +
            '<textarea class="gms-textarea gms-profile__output" id="gmsProfOutput" rows="14" readonly>' +
            ctx.esc(displayOut) + "</textarea>" +
            '<p class="gms-hint gms-profile__chars">' +
            (output ? output.length + " ký tự" : "Chưa có nội dung — bấm Tạo bằng AI") +
            (section === "business_description" ? " · GBP tối đa 750 ký tự" : "") +
            "</p></div></div></div>"
        );
    }

    async function loadServerDrafts(ctx, locId) {
        if (!ctx.authToken()) return;
        try {
            var res = await ctx.apiFetch("/profile/drafts?location_key=" + encodeURIComponent(locId));
            var drafts = res.data || [];
            drafts.forEach(function (d) {
                if (d.content_type && d.output_text) {
                    profileState.outputs[d.content_type] = d.output_text;
                    if (d.input) writeLsDraft(locId, d.content_type, { input: d.input, output: d.output_text });
                }
            });
        } catch (_e) {}
    }

    function loadLocalDrafts(locId) {
        SECTIONS.forEach(function (s) {
            var d = readLsDraft(locId, s.id);
            if (d && d.output && !profileState.outputs[s.id]) {
                profileState.outputs[s.id] = d.output;
            }
        });
    }

    function bindEvents(host, ctx) {
        if (host._gmsProfClick) {
            host.removeEventListener("click", host._gmsProfClick);
        }
        host._gmsProfClick = function (e) {
            var locId = ctx.location ? ctx.location.id : "default";
            var tab = e.target && e.target.closest ? e.target.closest("[data-gms-prof-tab]") : null;
            if (tab) {
                profileState.section = tab.getAttribute("data-gms-prof-tab");
                render(host, ctx);
                return;
            }
            if (e.target && e.target.id === "gmsProfBtnAi") runGenerate(host, ctx, locId);
            if (e.target && e.target.id === "gmsProfBtnCopy") copyOutput(host, ctx);
            if (e.target && e.target.id === "gmsProfBtnDraft") saveDraft(host, ctx, locId);
            if (e.target && e.target.id === "gmsProfBtnApply") applyProfile(host, ctx, locId);
        };
        host.addEventListener("click", host._gmsProfClick);
    }

    function render(host, ctx) {
        if (!host) return;
        host.innerHTML = renderHtml(ctx);
        fillForm(host, prefillFromLocation(ctx.location));
        var locId = ctx.location ? ctx.location.id : "default";
        var draft = readLsDraft(locId, profileState.section);
        if (draft && draft.input) fillForm(host, draft.input);
    }

    async function runGenerate(host, ctx, locId) {
        if (!ctx.authToken()) {
            ctx.showToast("Vui lòng đăng nhập để dùng AI.");
            if (typeof window.DigiSeoGoLogin === "function") window.DigiSeoGoLogin();
            return;
        }
        var input = readForm(host);
        if (!input.business_name && !input.industry) {
            ctx.showToast("Nhập ít nhất tên doanh nghiệp hoặc ngành nghề.");
            return;
        }
        profileState.loading = true;
        render(host, ctx);
        try {
            var res = await ctx.apiFetch("/profile/generate", {
                method: "POST",
                json: true,
                body: {
                    location_key: locId,
                    content_type: profileState.section,
                    input: input,
                },
            });
            var data = res.data || {};
            profileState.outputs[profileState.section] = data.content || "";
            profileState.warnings[profileState.section] = data.warnings || [];
            writeLsDraft(locId, profileState.section, { input: input, output: data.content });
            ctx.showToast("Đã tạo nội dung bằng AI.");
        } catch (e) {
            ctx.showToast((e && e.message) || "Không tạo được nội dung AI.");
        } finally {
            profileState.loading = false;
            render(host, ctx);
        }
    }

    function copyOutput(host, ctx) {
        var text = profileState.outputs[profileState.section] || "";
        if (!text) return;
        var display = profileState.section === "faq" ? formatFaqDisplay(text) : text;
        if (navigator.clipboard && navigator.clipboard.writeText) {
            navigator.clipboard.writeText(display).then(function () {
                ctx.showToast("Đã sao chép.");
            }).catch(function () {
                ctx.showToast("Không sao chép được — chọn thủ công.");
            });
        } else {
            var ta = host.querySelector("#gmsProfOutput");
            if (ta) {
                ta.removeAttribute("readonly");
                ta.select();
                try {
                    document.execCommand("copy");
                    ctx.showToast("Đã sao chép.");
                } catch (_e) {
                    ctx.showToast("Không sao chép được.");
                }
                ta.setAttribute("readonly", "readonly");
            }
        }
    }

    async function saveDraft(host, ctx, locId) {
        var input = readForm(host);
        var output = profileState.outputs[profileState.section] || "";
        if (!output) return;
        writeLsDraft(locId, profileState.section, { input: input, output: output });
        if (!ctx.authToken()) {
            ctx.showToast("Đã lưu nháp trên trình duyệt.");
            return;
        }
        try {
            await ctx.apiFetch("/profile/drafts", {
                method: "POST",
                json: true,
                body: {
                    location_key: locId,
                    content_type: profileState.section,
                    input: input,
                    output_text: output,
                },
            });
            ctx.showToast("Đã lưu nháp.");
        } catch (e) {
            ctx.showToast("Đã lưu local — server: " + ((e && e.message) || "lỗi"));
        }
    }

    async function applyProfile(host, ctx, locId) {
        var output = profileState.outputs[profileState.section] || "";
        if (!output) return;
        if (!ctx.authToken()) {
            ctx.showToast("Đăng nhập và kết nối GBP để áp dụng.");
            return;
        }
        try {
            await ctx.apiFetch("/profile/apply", {
                method: "POST",
                json: true,
                body: {
                    location_key: locId,
                    content_type: profileState.section,
                    content: output,
                },
            });
            ctx.showToast("Đã cập nhật mô tả lên Google Business Profile.");
        } catch (e) {
            ctx.showToast((e && e.message) || "Không áp dụng được lên GBP.");
        }
    }

    async function mount(host, ctx) {
        profileState.canApply = !!(ctx.location && ctx.location.source === "google_business_profile");
        profileState.outputs = {};
        profileState.warnings = {};
        var locId = ctx.location ? ctx.location.id : "default";
        loadLocalDrafts(locId);
        await loadServerDrafts(ctx, locId);
        render(host, ctx);
        bindEvents(host, ctx);
    }

    window.GmsProfile = {
        mount: mount,
        render: render,
        resetSection: function () {
            profileState.section = "business_description";
        },
    };
})();
