document.addEventListener("DOMContentLoaded", () => {
    const loadingOverlay = window.InventoryLoadingOverlay;
    document.querySelectorAll("[data-history-back]").forEach((link) => {
        link.addEventListener("click", (event) => {
            event.preventDefault();
            loadingOverlay?.show({ immediate: true });
            if (history.length > 1) history.back();
            else window.location.href = link.href;
        });
    });
});
