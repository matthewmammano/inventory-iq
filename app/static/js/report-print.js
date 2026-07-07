document.addEventListener("DOMContentLoaded", () => {
    const buttons = document.querySelectorAll("[data-report-print-url]");
    if (!buttons.length) return;

    const cleanupPrintState = () => {
        document.body.classList.remove("printing-report");
        document.querySelectorAll("[data-report-print-area]").forEach((printArea) => printArea.replaceChildren());
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
