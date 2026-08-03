/**
 * Khóa scroll body khi auth modal mở; đồng bộ class auth-modal-open.
 */
(function () {
    "use strict";

    function syncAuthModalScrollLock() {
        var modal = document.getElementById("authModal");
        var open = !!(modal && !modal.hidden);
        document.documentElement.classList.toggle("auth-modal-open", open);
        document.body.classList.toggle("auth-modal-open", open);
    }

    function bindModal(modal) {
        if (!modal || modal.dataset.digiseoAuthModalBound) return;
        modal.dataset.digiseoAuthModalBound = "1";
        new MutationObserver(syncAuthModalScrollLock).observe(modal, {
            attributes: true,
            attributeFilter: ["hidden"],
        });
    }

    function init() {
        bindModal(document.getElementById("authModal"));
        syncAuthModalScrollLock();
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }

    window.DigiSeoSyncAuthModalScrollLock = syncAuthModalScrollLock;
})();
