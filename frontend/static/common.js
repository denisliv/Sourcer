/**
 * AlfaHRService — shared utilities loaded on every page.
 * Handles: layout injection (header/footer), auth check, logout,
 * services dropdown, dev-toast, and common helper functions.
 */
(function () {
    "use strict";

    const API_BASE = window.ALFAHR_API_BASE || "";

    /* ── Layout injection ──────────────────────────────────────── */

    async function injectPartial(url, targetId) {
        const el = document.getElementById(targetId);
        if (!el) return;
        try {
            const resp = await fetch(url);
            if (resp.ok) el.innerHTML = await resp.text();
        } catch (_) { /* partial fetch failed — header/footer will be missing */ }
    }

    async function initLayout() {
        await Promise.all([
            injectPartial(API_BASE + "/static/partials/header.html", "app-header"),
            injectPartial(API_BASE + "/static/partials/footer.html", "app-footer"),
        ]);
        initLogout();
        initServicesDropdown();
        initAuth();
    }

    /* ── Auth check ────────────────────────────────────────────── */

    function initAuth() {
        const isLoginPage = window.location.pathname === "/login";
        if (isLoginPage) return;

        fetch(API_BASE + "/api/auth/me", { credentials: "include" })
            .then(r => {
                if (!r.ok) { window.location.href = "/login"; throw new Error("unauth"); }
                return r.json();
            })
            .then(u => {
                window._currentUser = u;
                if (u.is_admin) {
                    const el = document.getElementById("adminLink");
                    if (el) el.style.display = "";
                }
                document.dispatchEvent(new CustomEvent("alfahr:auth", { detail: u }));
            })
            .catch(() => {});
    }

    /* ── Logout ────────────────────────────────────────────────── */

    function initLogout() {
        const btn = document.getElementById("btnLogout");
        if (!btn) return;
        btn.addEventListener("click", async () => {
            await fetch(API_BASE + "/api/auth/logout", { method: "POST" });
            window.location.href = "/login";
        });
    }

    /* ── Services dropdown ─────────────────────────────────────── */

    function initServicesDropdown() {
        const btn = document.getElementById("servicesMenuBtn");
        const menu = document.getElementById("servicesMenu");
        if (btn && menu) {
            btn.addEventListener("click", (e) => {
                e.stopPropagation();
                const open = menu.classList.toggle("dropdown-open");
                btn.setAttribute("aria-expanded", open);
            });
            document.addEventListener("click", () => {
                menu.classList.remove("dropdown-open");
                btn.setAttribute("aria-expanded", "false");
            });
        }
        document.querySelectorAll(".dropdown-item-disabled").forEach(el => {
            el.addEventListener("click", (e) => {
                e.preventDefault();
                showDevToast("В разработке");
            });
        });
    }

    /* ── Dev toast ──────────────────────────────────────────────── */

    function showDevToast(msg) {
        const t = document.getElementById("devToast");
        if (!t) return;
        t.textContent = msg;
        t.style.display = "block";
        setTimeout(() => { t.style.display = "none"; }, 2500);
    }

    /* ── Helper functions (globally available) ─────────────────── */

    window.showMsg = function (el, msg) {
        el.textContent = msg;
        el.style.display = "block";
    };
    window.hideMsg = function (el) {
        el.style.display = "none";
    };
    window.escapeHtml = function (str) {
        const el = document.createElement("span");
        el.textContent = str;
        return el.innerHTML;
    };
    window.showDevToast = showDevToast;

    /* ── Init on DOM ready ─────────────────────────────────────── */

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", initLayout);
    } else {
        initLayout();
    }
})();
