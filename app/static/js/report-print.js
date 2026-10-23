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

    document.querySelectorAll("[data-report-print-open]").forEach((opener) => {
        const modal = document.getElementById(opener.dataset.reportPrintOpen);
        opener.addEventListener("click", () => modal?.classList.remove("hidden"));
    });
    document.querySelectorAll("[data-report-print-close]").forEach((closer) => {
        closer.addEventListener("click", () => closer.closest("[data-report-print-modal]")?.classList.add("hidden"));
    });

    buttons.forEach((button) => {
        // The `data-report-print-area` value is the target section's selector, so the attribute alone also matches the button.
        const printArea = findBySelector(button.dataset.reportPrintArea);
        if (!printArea) return;

        button.addEventListener("click", async () => {
            button.closest("[data-report-print-modal]")?.classList.add("hidden");
            try {
                await window.InventoryPrintPreview.printFetchedHtml(printUrl(button), printArea);
            } catch (_error) {
                window.InventoryFlash?.show("error", "Could not load the print report. Try again.");
            }
        });
    });
});
