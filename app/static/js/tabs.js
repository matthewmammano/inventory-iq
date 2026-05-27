function switchTo(tab) {
    if (!tab) return;
    document.querySelectorAll("[data-tab]").forEach((item) => item.classList.remove("active"));
    document.querySelectorAll(".tab-panel").forEach((panel) => panel.classList.add("hidden"));
    tab.classList.add("active");
    document.querySelector(tab.getAttribute("href")).classList.remove("hidden");
}

window.InventoryTabs = { switchTo };

document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll("[data-tab]:not([data-manual-tab])").forEach((tab) => {
        tab.addEventListener("click", (event) => {
            event.preventDefault();
            switchTo(tab);
        });
    });
});
