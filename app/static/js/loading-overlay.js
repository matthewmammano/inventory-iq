document.addEventListener("DOMContentLoaded", () => {
    const overlay = document.querySelector("#loading-overlay");
    if (!overlay) return;

    const SHOW_DELAY_MS = 180;
    let showTimer = null;

    function setVisible(visible) {
        document.body.classList.toggle("loading-active", visible);
        overlay.classList.toggle("hidden", !visible);
        overlay.setAttribute("aria-hidden", visible ? "false" : "true");
    }

    function hide() {
        if (showTimer) {
            clearTimeout(showTimer);
            showTimer = null;
        }
        setVisible(false);
    }

    function show(options = {}) {
        const immediate = options.immediate === true;
        if (showTimer) {
            clearTimeout(showTimer);
            showTimer = null;
        }
        if (immediate) {
            setVisible(true);
            return;
        }
        showTimer = window.setTimeout(() => {
            showTimer = null;
            setVisible(true);
        }, SHOW_DELAY_MS);
    }

    function shouldHandleLink(link, event) {
        const href = link.getAttribute("href") || "";
        if (!href || href.startsWith("#") || href.startsWith("javascript:")) return false;
        if (link.hasAttribute("download")) return false;
        if (link.target && link.target !== "_self") return false;
        if (event.defaultPrevented) return false;
        if (event.button !== 0) return false;
        if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return false;
        return true;
    }

    function showWhenEventCompletes(event) {
        window.setTimeout(() => {
            if (!event.defaultPrevented) show();
        }, 0);
    }

    document.addEventListener("click", (event) => {
        if (!(event.target instanceof Element)) return;
        const link = event.target.closest("a[href]");
        if (!link || !shouldHandleLink(link, event)) return;
        showWhenEventCompletes(event);
    }, true);

    document.addEventListener("submit", (event) => {
        const form = event.target;
        if (!(form instanceof HTMLFormElement)) return;
        if (event.defaultPrevented) return;
        showWhenEventCompletes(event);
    }, true);

    window.addEventListener("pageshow", hide);
    window.addEventListener("load", hide);
    document.addEventListener("visibilitychange", () => {
        if (document.visibilityState === "visible") hide();
    });

    window.InventoryLoadingOverlay = { show, hide };
    hide();
});
