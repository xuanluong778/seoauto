/**
 * Seoauto theme boot — reads digiseo_system_prefs_v1, sets data-theme on <html>.
 * Exposes window.__digiseoApplySystemPrefs for Settings → System tab.
 */
(function (global) {
    const LS = "digiseo_system_prefs_v1";

    function applyTheme(theme) {
        const t =
            theme === "light" || theme === "dark" || theme === "system" ? theme : "dark";
        const html = global.document && global.document.documentElement;
        if (!html) return;
        html.setAttribute("data-theme", t);
        if (t === "system") {
            const dark = global.matchMedia("(prefers-color-scheme: dark)").matches;
            html.setAttribute("data-theme-resolved", dark ? "dark" : "light");
        } else {
            html.setAttribute("data-theme-resolved", t);
        }
    }

    function applyLang(lang) {
        const l = lang === "vi" || lang === "en" ? lang : "vi";
        const html = global.document && global.document.documentElement;
        if (html) html.setAttribute("lang", l);
    }

    function readPrefs() {
        try {
            let raw = global.localStorage.getItem(LS);
            if (!raw) raw = global.localStorage.getItem("genseo_system_prefs_v1");
            return raw ? JSON.parse(raw) : {};
        } catch (_) {
            return {};
        }
    }

    global.__digiseoApplySystemPrefs = function (prefs) {
        if (!prefs || typeof prefs !== "object") return;
        try {
            global.localStorage.setItem(LS, JSON.stringify(prefs));
        } catch (_) {}
        if (prefs.theme) applyTheme(prefs.theme);
        if (prefs.language) {
            applyLang(prefs.language);
            if (global.DigiSeoI18n) global.DigiSeoI18n.apply(prefs.language);
        }
        global.dispatchEvent(new CustomEvent("digiseo:system-prefs", { detail: prefs }));
    };

    try {
        const p = readPrefs();
        applyTheme(p.theme);
        applyLang(p.language);
    } catch (_) {
        applyTheme("dark");
    }

    try {
        const mq = global.matchMedia("(prefers-color-scheme: dark)");
        const onChange = function () {
            const p = readPrefs();
            if (p.theme === "system") applyTheme("system");
        };
        if (mq.addEventListener) mq.addEventListener("change", onChange);
        else if (mq.addListener) mq.addListener(onChange);
    } catch (_) {}
})(typeof window !== "undefined" ? window : globalThis);
