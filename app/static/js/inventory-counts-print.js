document.addEventListener("DOMContentLoaded", () => {
    const button = document.querySelector("#open-counts-print");
    const printArea = document.querySelector("#counts-print-area");
    if (!button || !printArea) return;

    button.addEventListener("click", async () => {
        window.InventoryLoadingOverlay?.show({ immediate: true });
        try {
            const response = await fetch(button.dataset.printUrl, { headers: { "X-Requested-With": "fetch" } });
            if (!response.ok) throw new Error("Could not load print report.");
            printArea.innerHTML = await response.text();
            window.InventoryLoadingOverlay?.hide();
            document.body.classList.add("printing-report");
            window.print();
        } catch (_error) {
            window.InventoryLoadingOverlay?.hide();
        }
    });

    window.addEventListener("afterprint", () => {
        document.body.classList.remove("printing-report");
        printArea.replaceChildren();
    });
});
