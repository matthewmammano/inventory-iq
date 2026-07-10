document.addEventListener("DOMContentLoaded", () => {
    const buttons = document.querySelectorAll("[data-report-print-url]");
    if (!buttons.length) return;

    // Buttons carry a `data-report-print-area` attribute whose *value* is the target
    // section's selector, so a bare `[data-report-print-area]` query also matches the
    // buttons themselves. Resolve each button's target section once and clear only those.
    const printAreas = [...buttons].map((button) => document.querySelector(button.dataset.reportPrintArea || "")).filter(Boolean);

    const cleanupPrintState = () => {
        document.body.classList.remove("printing-report");
        printAreas.forEach((printArea) => printArea.replaceChildren());
    };

    buttons.forEach((button) => {
        const printArea = document.querySelector(button.dataset.reportPrintArea || "");
        if (!printArea) return;

        button.addEventListener("click", async () => {
            window.InventoryLoadingOverlay?.show({ immediate: true });
            try {
                const response = await fetch(button.dataset.reportPrintUrl, { headers: { "X-Requested-With": "fetch" } });
                if (!response.ok) throw new Error("Could not load print report.");
                printArea.innerHTML = await response.text();
                window.InventoryLoadingOverlay?.hide();
                document.body.classList.add("printing-report");
                window.print();
                window.setTimeout(cleanupPrintState, 250);
            } catch (_error) {
                window.InventoryLoadingOverlay?.hide();
                cleanupPrintState();
            }
        });
    });

    window.addEventListener("afterprint", cleanupPrintState);
    document.addEventListener("visibilitychange", () => {
        if (!document.hidden) window.setTimeout(cleanupPrintState, 250);
    });
});
