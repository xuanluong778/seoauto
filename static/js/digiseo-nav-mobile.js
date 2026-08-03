/**
 * Mobile top nav — nút Menu xổ dropdown.
 */
(function () {
    var BP = 820;
    var OPEN_CLASS = "digiseo-nav-open";
    var suppressCloseUntil = 0;

    function isMobile() {
        return window.matchMedia("(max-width: " + BP + "px)").matches;
    }

    function strips() {
        return Array.prototype.slice.call(
            document.querySelectorAll("#digiseoTopNavStrip, .nav-strip, .pricing-page-nav, .site-header")
        );
    }

    function toggleFor(el) {
        return el ? el.querySelector(".digiseo-nav-toggle") : null;
    }

    function menuFor(el) {
        return el ? el.querySelector(".digiseo-nav-links") : null;
    }

    function setOpen(container, open) {
        if (!container) return;
        var btn = toggleFor(container);
        var menu = menuFor(container);
        var topNav = container.querySelector(".digiseo-top-nav");

        if (open) {
            strips().forEach(function (c) {
                if (c !== container) setOpen(c, false);
            });
            container.classList.add(OPEN_CLASS);
            if (topNav) topNav.classList.add(OPEN_CLASS);
            document.body.classList.add("digiseo-nav-menu-open");
            if (btn) {
                btn.setAttribute("aria-expanded", "true");
                btn.setAttribute("aria-label", "Đóng menu");
            }
            if (menu) {
                menu.classList.add("is-open");
                menu.setAttribute("aria-hidden", "false");
                menu.removeAttribute("hidden");
            }
        } else {
            container.classList.remove(OPEN_CLASS);
            if (topNav) topNav.classList.remove(OPEN_CLASS);
            if (!strips().some(function (c) { return c.classList.contains(OPEN_CLASS); })) {
                document.body.classList.remove("digiseo-nav-menu-open");
            }
            if (btn) {
                btn.setAttribute("aria-expanded", "false");
                btn.setAttribute("aria-label", "Mở menu");
            }
            if (menu) {
                menu.classList.remove("is-open");
                menu.setAttribute("aria-hidden", "true");
            }
        }
    }

    function closeAll() {
        strips().forEach(function (c) {
            setOpen(c, false);
        });
        document.body.classList.remove("digiseo-nav-menu-open");
    }

    function bindContainer(container) {
        if (!container || container.dataset.digiseoNavMobileBound) return;
        container.dataset.digiseoNavMobileBound = "1";

        var btn = toggleFor(container);
        var menu = menuFor(container);
        if (!btn || !menu) return;

        menu.setAttribute("aria-hidden", "true");

        btn.addEventListener("click", function (e) {
            e.preventDefault();
            e.stopPropagation();
            suppressCloseUntil = Date.now() + 350;
            var open = !container.classList.contains(OPEN_CLASS);
            setOpen(container, open);
        });

        menu.querySelectorAll("a").forEach(function (a) {
            a.addEventListener("click", function () {
                if (isMobile()) setOpen(container, false);
            });
        });
    }

    function onDocClick(e) {
        if (!isMobile()) return;
        if (Date.now() < suppressCloseUntil) return;
        var t = e.target;
        if (t.closest && t.closest(".digiseo-nav-toggle, .digiseo-nav-links, .digiseo-nav-bar")) return;
        closeAll();
    }

    function onKey(e) {
        if (e.key === "Escape") closeAll();
    }

    function onResize() {
        if (!isMobile()) {
            closeAll();
            strips().forEach(function (c) {
                var menu = menuFor(c);
                if (menu) {
                    menu.removeAttribute("hidden");
                    menu.setAttribute("aria-hidden", "false");
                }
            });
        }
    }

    function init() {
        strips().forEach(bindContainer);
        document.addEventListener("click", onDocClick);
        document.addEventListener("keydown", onKey);
        window.addEventListener("resize", onResize);
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();
