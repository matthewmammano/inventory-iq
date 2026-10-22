// An empty selector is a SyntaxError, and a report without a detail toggle has no selector at all.
const findBySelector = (selector) => (selector ? document.querySelector(selector) : null);

const printUrl = (button) => {
    const url = new URL(button.dataset.reportPrintUrl, window.location.origin);
    if (findBySelector(button.dataset.reportPrintDetailed)?.checked) url.searchParams.set("detailed", "1");
    return url.toString();
};

document.addEventListener("DOMContentLoaded", () => {
    const buttons = document.querySelectorAll("[data-report-print-url]");
    if (!buttons.length) return;

    // Buttons carry a `data-report-print-area` attribute whose *value* is the target
    // section's selector, so a bare `[data-report-print-area]` query also matches the
    // buttons themselves. Resolve each button's target section once and clear only those.
    const printAreas = [...buttons].map((button) => findBySelector(button.dataset.reportPrintArea)).filter(Boolean);

    const cleanupPrintState = () => {
        document.body.classList.remove("printing-report");
        printAreas.forEach((printArea) => printArea.replaceChildren());
    };

    document.querySelectorAll("[data-report-print-open]").forEach((opener) => {
        const modal = document.getElementById(opener.dataset.reportPrintOpen);
        opener.addEventListener("click", () => modal?.classList.remove("hidden"));
    });
    document.querySelectorAll("[data-report-print-close]").forEach((closer) => {
        closer.addEventListener("click", () => closer.closest("[data-report-print-modal]")?.classList.add("hidden"));
    });

    buttons.forEach((button) => {
        const printArea = findBySelector(button.dataset.reportPrintArea);
        if (!printArea) return;

        button.addEventListener("click", async () => {
            button.closest("[data-report-print-modal]")?.classList.add("hidden");
            window.InventoryLoadingOverlay?.show({ immediate: true });
            try {
                const response = await fetch(printUrl(button), { headers: { "X-Requested-With": "fetch" } });
                if (!response.ok) throw new Error("Could not load print report.");
                printArea.innerHTML = await response.text();
                window.InventoryLoadingOverlay?.hide();
                document.body.classList.add("printing-report");
                window.print();
                window.setTimeout(cleanupPrintState, 250);
            } catch (_error) {
                window.InventoryLoadingOverlay?.hide();
                cleanupPrintState();
                window.InventoryFlash?.show("error", "Could not load the print report. Try again.");
            }
        });
    });

    window.addEventListener("afterprint", cleanupPrintState);
    document.addEventListener("visibilitychange", () => {
        if (!document.hidden) window.setTimeout(cleanupPrintState, 250);
    });
});
