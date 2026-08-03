// Load TinyMCE to make Content editor like WordPress.
// If the CDN is blocked/unavailable, we keep the textarea as-is.
(function () {
    window.__USE_TINYMCE = false;
    if (!window.__USE_TINYMCE) {
        window.__tinymceReady = false;
        return;
    }
    const sources = [
        "https://cdn.jsdelivr.net/npm/tinymce@6/tinymce.min.js",
        "https://cdnjs.cloudflare.com/ajax/libs/tinymce/6.8.6/tinymce.min.js",
        "https://unpkg.com/tinymce@6/tinymce.min.js",
    ];
    const loadAt = (idx) => {
        if (idx >= sources.length) {
            window.__tinymceReady = false;
            return;
        }
        const s = document.createElement("script");
        s.referrerPolicy = "origin";
        s.src = sources[idx];
        s.onload = () => { window.__tinymceReady = true; };
        s.onerror = () => loadAt(idx + 1);
        document.head.appendChild(s);
    };
    loadAt(0);
})();
