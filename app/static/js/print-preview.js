const PRINT_BODY_CLASS = "printing-report";
const CLEANUP_DELAY_MS = 250;

const printAreas = new Set();

function clearPrintState() {
    document.body.classList.remove(PRINT_BODY_CLASS);
    printAreas.forEach((printArea) => printArea.replaceChildren());
}

// Printing has no completion event, so the injected markup is cleared on every signal the browser does give.
async function printFetchedHtml(url, printArea) {
    printAreas.add(printArea);
    window.InventoryLoadingOverlay?.show({ immediate: true });
    try {
        const response = await fetch(url, { headers: { "X-Requested-With": "fetch" } });
        if (!response.ok) throw new Error(await response.text());
        printArea.innerHTML = await response.text();
        window.InventoryLoadingOverlay?.hide();
        document.body.classList.add(PRINT_BODY_CLASS);
        window.print();
        window.setTimeout(clearPrintState, CLEANUP_DELAY_MS);
    } catch (error) {
        window.InventoryLoadingOverlay?.hide();
        clearPrintState();
        throw error;
    }
}

window.addEventListener("afterprint", clearPrintState);
document.addEventListener("visibilitychange", () => {
    if (!document.hidden) window.setTimeout(clearPrintState, CLEANUP_DELAY_MS);
});

window.InventoryPrintPreview = { printFetchedHtml, clearPrintState };
