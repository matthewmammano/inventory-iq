document.addEventListener("DOMContentLoaded", () => {
    const modal = document.querySelector("#tab-confirm-modal");
    const changeList = document.querySelector("#tab-change-list");
    if (!modal || !changeList) return;

    let pendingTab = null;
    let pendingUrl = "";
    let modalMode = "tab";
    const changedInputs = () => {
        const activePanel = document.querySelector(".tab-panel:not(.hidden)");
        if (!activePanel) return [];
        return [...activePanel.querySelectorAll("[data-original-value]")]
            .filter((input) => input.value !== input.dataset.originalValue);
    };

    document.querySelectorAll("[data-tab]").forEach((tab) => {
        tab.addEventListener("click", (event) => {
            event.preventDefault();
            const inputs = changedInputs();
            if (inputs.length === 0) {
                window.InventoryTabs.switchTo(tab);
                return;
            }
            openModal("tab", inputs, tab);
        });
    });

    document.querySelector("[data-bulk-back]")?.addEventListener("click", (event) => {
        const inputs = changedInputs();
        if (inputs.length === 0) return;
        event.preventDefault();
        openModal("back", inputs, null, event.currentTarget.href);
    });

    document.querySelector("#cancel-tab-switch").addEventListener("click", () => {
        modal.classList.add("hidden");
        pendingUrl = "";
        pendingTab = null;
    });
    document.querySelector("#confirm-tab-switch").addEventListener("click", () => {
        changedInputs().forEach((input) => {
            input.value = input.dataset.originalValue;
            input.classList.remove("changed");
        });
        modal.classList.add("hidden");
        if (modalMode === "back") {
            window.location.href = pendingUrl;
            return;
        }
        window.InventoryTabs.switchTo(pendingTab);
        pendingUrl = "";
        pendingTab = null;
    });

    function openModal(mode, inputs, tab = null, url = "") {
        modalMode = mode;
        pendingTab = tab;
        pendingUrl = url;
        document.querySelector("#tab-confirm-message").textContent = mode === "back"
            ? "This table has unsaved changes. Go back without saving?"
            : "This table has unsaved changes. Switch tabs without saving?";
        document.querySelector("#confirm-tab-switch").textContent = mode === "back"
            ? "Go Back Without Saving"
            : "Switch Without Saving";
        changeList.innerHTML = inputs.map((input) =>
            `<div class="change-item">${input.getAttribute("aria-label")}: ${input.dataset.originalValue} to ${input.value}</div>`
        ).join("");
        modal.classList.remove("hidden");
    }
});
