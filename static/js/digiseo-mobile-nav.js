/**
 * SEOAuto — mobile nav drawer ≤820px.
 * Menu portaled ra body để thoát stacking context của header.
 */
(function () {
    "use strict";

    var BP = 820;
    var OPEN_CLASS = "digiseo-nav-open";
    var MENU_OPEN = "is-open";
    var PORTAL_CLASS = "digiseo-nav-menu-portaled";
    var suppressCloseUntil = 0;
    var portal = { menu: null, placeholder: null, parent: null };

    function isCompactNav() {
        return window.matchMedia("(max-width: " + BP + "px)").matches;
    }

    function strips() {
        var seen = new Set();
        return Array.prototype.slice.call(
            document.querySelectorAll("#digiseoTopNavStrip, .nav-strip, .pricing-page-nav, .site-header")
        ).filter(function (el) {
            if (seen.has(el)) return false;
            seen.add(el);
            return true;
        });
    }

    function toggleFor(el) {
        return el ? el.querySelector(".digiseo-nav-toggle") : null;
    }

    function menuFor(el) {
        return el ? el.querySelector(".digiseo-nav-links") : null;
    }

    function getMenuGlobal() {
        return document.getElementById("digiseoNavMenu");
    }

    function purgeBackdrop() {
        var el = document.getElementById("digiseoNavBackdrop");
        if (el && el.parentNode) el.parentNode.removeChild(el);
    }

    function portalMenuOpen(menu) {
        if (!menu || menu.classList.contains(PORTAL_CLASS)) return;
        portal.menu = menu;
        portal.parent = menu.parentNode;
        if (!portal.parent) return;
        portal.placeholder = document.createComment("digiseo-nav-menu-anchor");
        portal.parent.insertBefore(portal.placeholder, menu);
        menu.classList.add(PORTAL_CLASS);
        document.body.appendChild(menu);
    }

    function portalMenuClose(menu) {
        if (!menu) return;
        menu.classList.remove(PORTAL_CLASS);
        if (portal.placeholder && portal.parent) {
            portal.parent.insertBefore(menu, portal.placeholder);
            portal.placeholder.remove();
        }
        portal.menu = null;
        portal.placeholder = null;
        portal.parent = null;
    }

    function lockBody(lock) {
        if (!isCompactNav()) return;
        document.documentElement.classList.toggle("digiseo-nav-scroll-lock", lock);
        document.body.classList.toggle("digiseo-nav-scroll-lock", lock);
    }

    function anyOpen() {
        return strips().some(function (c) {
            return c.classList.contains(OPEN_CLASS);
        });
    }

    function applyContainerState(container, open) {
        var btn = toggleFor(container);
        var menu = menuFor(container) || getMenuGlobal();
        var topNav = container.querySelector(".digiseo-top-nav");

        if (open) {
            container.classList.add(OPEN_CLASS);
            if (topNav) topNav.classList.add(OPEN_CLASS);
            document.body.classList.add("digiseo-nav-menu-open");
            if (btn) {
                btn.setAttribute("aria-expanded", "true");
                btn.setAttribute("aria-label", "Đóng menu");
            }
            if (menu) {
                menu.classList.add(MENU_OPEN);
                menu.setAttribute("aria-hidden", "false");
                menu.removeAttribute("hidden");
                portalMenuOpen(menu);
            }
        } else {
            container.classList.remove(OPEN_CLASS);
            if (topNav) topNav.classList.remove(OPEN_CLASS);
            if (btn) {
                btn.setAttribute("aria-expanded", "false");
                btn.setAttribute("aria-label", "Mở menu");
            }
            if (menu) {
                menu.classList.remove(MENU_OPEN);
                menu.setAttribute("aria-hidden", "true");
                portalMenuClose(menu);
            }
            if (!anyOpen()) {
                document.body.classList.remove("digiseo-nav-menu-open");
                lockBody(false);
            }
        }
    }

    function setOpen(container, open) {
        if (!container) return;
        if (open) {
            strips().forEach(function (c) {
                if (c !== container) applyContainerState(c, false);
            });
            applyContainerState(container, true);
            lockBody(true);
        } else {
            applyContainerState(container, false);
        }
    }

    function closeAll() {
        var menu = getMenuGlobal();
        strips().forEach(function (c) {
            applyContainerState(c, false);
        });
        document.body.classList.remove("digiseo-nav-menu-open");
        if (menu) portalMenuClose(menu);
        lockBody(false);
        purgeBackdrop();
    }

    function onMenuLinkActivate(e, link) {
        if (!isCompactNav()) return;
        var menu = getMenuGlobal();
        if (!menu || !menu.classList.contains(MENU_OPEN)) return;
        closeAll();
    }

    function bindMenuLinks(menu) {
        if (!menu || menu.dataset.digiseoNavLinksBound) return;
        menu.dataset.digiseoNavLinksBound = "1";

        menu.querySelectorAll("a[href]").forEach(function (link) {
            link.addEventListener("click", function () {
                onMenuLinkActivate(null, link);
            });
        });
    }

    function bindContainer(container) {
        if (!container || container.dataset.digiseoMobileNavBound) return;
        container.dataset.digiseoMobileNavBound = "1";

        var btn = toggleFor(container);
        var menu = menuFor(container) || getMenuGlobal();
        if (!btn || !menu) return;

        menu.setAttribute("aria-hidden", "true");
        bindMenuLinks(menu);

        btn.addEventListener("click", function (e) {
            e.preventDefault();
            e.stopPropagation();
            suppressCloseUntil = Date.now() + 400;
            setOpen(container, !container.classList.contains(OPEN_CLASS));
        });
    }

    function onDocClick(e) {
        if (!isCompactNav()) return;
        if (Date.now() < suppressCloseUntil) return;
        var t = e.target;
        if (!t || !t.closest) return;
        if (t.closest(".digiseo-nav-toggle, #digiseoNavMenu, .digiseo-nav-bar, .digiseo-nav-menu-portaled")) return;
        closeAll();
    }

    function onKey(e) {
        if (e.key === "Escape") closeAll();
    }

    function onResize() {
        if (!isCompactNav()) {
            closeAll();
            var menu = getMenuGlobal();
            if (menu) {
                menu.removeAttribute("hidden");
                menu.setAttribute("aria-hidden", "false");
                menu.classList.remove(MENU_OPEN);
                portalMenuClose(menu);
            }
        }
    }

    function init() {
        purgeBackdrop();
        strips().forEach(bindContainer);
        var menu = getMenuGlobal();
        if (menu) bindMenuLinks(menu);
        document.addEventListener("click", onDocClick, true);
        document.addEventListener("keydown", onKey);
        window.addEventListener("resize", onResize);
    }

    purgeBackdrop();

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }

    window.digiseoCloseMobileNav = closeAll;
})();
