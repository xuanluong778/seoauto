/**
 * Seoauto UI i18n — vi / en. Language from localStorage digiseo_system_prefs_v1.
 */
(function (global) {
    const LS_KEY = "digiseo_system_prefs_v1";

    const STR = {
        en: {
            "nav.brand": "Seoauto",
            "nav.dashboard": "Dashboard",
            "nav.technical": "Technical",
            "nav.seo_score": "SEO Score",
            "nav.index_control": "Index Control",
            "nav.google_map_seo": "Google Map",
            "nav.content_ai": "Content AI",
            "nav.social_auto": "Social Auto",
            "nav.chatbot_cskh": "Chatbot CSKH",
            "nav.rank_tracking": "Rank Tracking",
            "nav.keyword": "Keyword",
            "nav.keyword_research": "Keyword Research",
            "nav.keyword_clustering": "Keyword Clustering",
            "nav.schema": "Schema",
            "nav.settings": "Settings",
            "nav.admin": "Administrator",
            "nav.account": "Account",
            "nav.affiliate": "Affiliate",
            "nav.api_keys": "API Keys",
            "nav.ai_provider": "AI Provider",
            "nav.ai_kb": "AI Knowledge Base",
            "nav.publishing": "Publishing",
            "nav.search_console": "Search Console",
            "nav.system": "System",
            "auth.login": "Sign in",
            "auth.logout": "Sign out",
            "auth.open_tool": "Open tool",
            "nav.aria": "Main menu",
            "nav.keyword_tools_aria": "Keyword tools",
            "settings.title": "Settings",
            "settings.lead":
                "Configure AI, API keys and integrations — items below are the working framework; most features connect to the backend gradually.",
            "settings.sb.account": "Account",
            "settings.sb.affiliate": "Affiliate",
            "settings.sb.api_keys": "API Keys",
            "settings.sb.ai_provider": "AI Provider",
            "settings.sb.ai_kb": "AI Knowledge Base",
            "settings.sb.publishing": "Publishing",
            "settings.sb.search_console": "Search Console",
            "settings.sb.system": "System",
            "settings.sb.aria": "Settings sections",
            "system.title": "System",
            "system.lead": "Appearance, language, startup, and background processing defaults.",
            "system.appearance": "Appearance",
            "system.display_mode": "Display mode",
            "system.theme_light": "Light",
            "system.theme_light_desc": "Light interface",
            "system.theme_dark": "Dark",
            "system.theme_dark_desc": "Dark interface",
            "system.theme_auto": "Automatic",
            "system.theme_auto_desc": "Follow system setting",
            "system.display_language": "Display language",
            "system.lang_lead":
                "Choose the display language of the app. Changes apply immediately without restart.",
            "system.startup_title": "Start with the operating system",
            "system.startup_desc": "Launch Seoauto automatically when the computer starts",
            "system.startup_note":
                "Saved for your account. Desktop app builds can read this preference later.",
            "system.processing": "Processing",
            "system.batch_size": "Batch size",
            "system.batch_hint": "Number of videos processed per batch",
            "system.batch_tip": "Number of videos processed per batch",
            "system.max_retries": "Max retries",
            "system.retry_hint": "How many times a failed task is retried",
            "system.retry_tip": "How many times a failed task is retried",
            "system.stuck_timeout": "Stuck timeout (minutes)",
            "system.stuck_hint": "Timeout threshold used to detect stuck tasks",
            "system.stuck_tip": "Timeout threshold used to detect stuck tasks",
            "system.saved": "Saved.",
            "system.save_err": "Could not save settings.",
            "system.need_login": "Please sign in to save system settings.",
            "lang.active": "ACTIVE",
        },
        vi: {
            "nav.brand": "Seoauto",
            "nav.dashboard": "Dashboard",
            "nav.technical": "Technical",
            "nav.seo_score": "Chấm điểm SEO",
            "nav.index_control": "Index Control",
            "nav.google_map_seo": "Google Map",
            "nav.content_ai": "Content AI",
            "nav.social_auto": "Social Auto",
            "nav.chatbot_cskh": "Chatbot CSKH",
            "nav.rank_tracking": "Theo dõi thứ hạng",
            "nav.keyword": "Keyword",
            "nav.keyword_research": "Nghiên cứu từ khóa",
            "nav.keyword_clustering": "Gom nhóm từ khóa",
            "nav.schema": "Schema",
            "nav.settings": "Cài đặt",
            "nav.admin": "Quản trị viên",
            "nav.account": "Tài khoản",
            "nav.affiliate": "Affiliate",
            "nav.api_keys": "Khóa API",
            "nav.ai_provider": "Nhà cung cấp AI",
            "nav.ai_kb": "AI Knowledge Base",
            "nav.publishing": "Xuất bản",
            "nav.search_console": "Search Console",
            "nav.system": "Hệ thống",
            "auth.login": "Đăng nhập",
            "auth.logout": "Đăng xuất",
            "auth.open_tool": "Vào công cụ",
            "nav.aria": "Menu chính",
            "nav.keyword_tools_aria": "Công cụ từ khóa",
            "settings.title": "Cài đặt",
            "settings.lead":
                "Cấu hình AI, khóa API và tích hợp — các mục dưới đây là khung làm việc; phần lớn tính năng sẽ được nối dần với backend.",
            "settings.sb.account": "Tài khoản",
            "settings.sb.affiliate": "Affiliate",
            "settings.sb.api_keys": "Khóa API",
            "settings.sb.ai_provider": "Nhà cung cấp AI",
            "settings.sb.ai_kb": "AI Knowledge Base",
            "settings.sb.publishing": "Xuất bản",
            "settings.sb.search_console": "Search Console",
            "settings.sb.system": "Hệ thống",
            "settings.sb.aria": "Mục cài đặt",
            "system.title": "Hệ thống",
            "system.lead": "Giao diện, ngôn ngữ, khởi động và tham số xử lý nền.",
            "system.appearance": "Giao diện",
            "system.display_mode": "Chế độ hiển thị",
            "system.theme_light": "Sáng",
            "system.theme_light_desc": "Giao diện sáng",
            "system.theme_dark": "Tối",
            "system.theme_dark_desc": "Giao diện tối",
            "system.theme_auto": "Tự động",
            "system.theme_auto_desc": "Theo hệ điều hành",
            "system.display_language": "Ngôn ngữ hiển thị",
            "system.lang_lead":
                "Chọn ngôn ngữ giao diện. Thay đổi có hiệu lực ngay, không cần khởi động lại.",
            "system.startup_title": "Khởi động cùng hệ đống",
            "system.startup_desc": "Tự mở Seoauto khi máy tính bật",
            "system.startup_note": "Lưu theo tài khoản. Bản desktop có thể đọc tuỳ chọn này sau.",
            "system.processing": "Xử lý",
            "system.batch_size": "Kích thước batch",
            "system.batch_hint": "Số video xử lý mỗi batch",
            "system.batch_tip": "Số video xử lý mỗi batch",
            "system.max_retries": "Số lần thử lại tối đa",
            "system.retry_hint": "Số lần thử lại khi tác vụ lỗi",
            "system.retry_tip": "Số lần thử lại khi tác vụ lỗi",
            "system.stuck_timeout": "Timeout kẹt (phút)",
            "system.stuck_hint": "Ngưỡng phát hiện tác vụ bị kẹt",
            "system.stuck_tip": "Ngưỡng phát hiện tác vụ bị kẹt",
            "system.saved": "Đã lưu.",
            "system.save_err": "Không lưu được cài đặt.",
            "system.need_login": "Vui lòng đăng nhập để lưu cài đặt hệ thống.",
            "lang.active": "ĐANG DÙNG",
        },
    };

    function readLang() {
        try {
            const raw = global.localStorage.getItem(LS_KEY);
            if (raw) {
                const p = JSON.parse(raw);
                if (p.language === "vi" || p.language === "en") return p.language;
            }
        } catch (_) {}
        return "en";
    }

    function t(lang, key) {
        const L = lang === "vi" ? "vi" : "en";
        const pack = STR[L] || STR.en;
        if (pack[key] !== undefined) return pack[key];
        return STR.en[key] || key;
    }

    function apply(lang) {
        const L = lang === "vi" ? "vi" : "en";
        const html = global.document && global.document.documentElement;
        if (html) html.setAttribute("lang", L);

        const root = global.document;
        if (!root) return;

        root.querySelectorAll("[data-i18n]").forEach((el) => {
            const key = el.getAttribute("data-i18n");
            if (!key) return;
            const val = t(L, key);
            if (el.hasAttribute("data-i18n-placeholder")) {
                el.placeholder = val;
            } else {
                el.textContent = val;
            }
        });

        root.querySelectorAll("[data-i18n-html]").forEach((el) => {
            const key = el.getAttribute("data-i18n-html");
            if (key) el.innerHTML = t(L, key);
        });

        root.querySelectorAll("[data-i18n-title]").forEach((el) => {
            const key = el.getAttribute("data-i18n-title");
            if (key) el.title = t(L, key);
        });

        root.querySelectorAll("[data-i18n-chevron]").forEach((el) => {
            const key = el.getAttribute("data-i18n-chevron");
            if (key) el.textContent = t(L, key) + " ▾";
        });

        root.querySelectorAll("[data-i18n-aria]").forEach((el) => {
            const key = el.getAttribute("data-i18n-aria");
            if (key) el.setAttribute("aria-label", t(L, key));
        });

        root.querySelectorAll("[data-lang-badge]").forEach((el) => {
            const code = el.getAttribute("data-lang-badge");
            if (code === L) {
                el.textContent = t(L, "lang.active");
                el.hidden = false;
            } else if (code === "vi" || code === "en") {
                el.hidden = true;
            }
        });

        try {
            global.dispatchEvent(new CustomEvent("digiseo:i18n-applied", { detail: { lang: L } }));
        } catch (_) {}
    }

    function init() {
        apply(readLang());
    }

    global.DigiSeoI18n = {
        STR,
        LS_KEY,
        readLang,
        t,
        apply,
        init,
    };
})(typeof window !== "undefined" ? window : globalThis);
