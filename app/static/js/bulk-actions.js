document.addEventListener("DOMContentLoaded", () => {
    const MAX_MODAL_CHANGES = 5;
    const modal = document.querySelector("#tab-confirm-modal");
    const changeList = document.querySelector("#tab-change-list");
    const back = document.querySelector("[data-bulk-back]");
    const saveButton = document.querySelector("#save-bulk-button");
    const loadingOverlay = window.InventoryLoadingOverlay;
    if (!modal || !changeList || !back) return;

    const quantityInputs = [...document.querySelectorAll("[data-count-input], [data-restock-input]")];
    const changedInputs = () => [...document.querySelectorAll("[data-original-value]")]
        .filter((input) => input.value !== input.dataset.originalValue);

    function renderDirtyState() {
        saveButton?.classList.toggle("hidden", changedInputs().length === 0);
    }

    function updateRequiredCounts() {
        document.querySelectorAll("[data-count-cell]").forEach((cell) => {
            const input = cell.querySelector("[data-count-input]");
            const invalid = isInvalidQuantity(input);
            cell.classList.toggle("invalid-cell", invalid);
            input?.classList.toggle("invalid", invalid);
        });
        document.querySelectorAll("tbody tr").forEach((row) => {
            const rowRequiresCounts = [...row.querySelectorAll("[data-count-required='1']")];
            const hasRestock = [...row.querySelectorAll("[data-restock-input]")]
                .some((input) => Number(input.value || 0) > 0);
            rowRequiresCounts.forEach((cell) => {
                const countInput = cell.querySelector("[data-count-input]");
                const hasCount = Boolean(countInput && countInput.value !== "");
                cell.classList.toggle("invalid-cell", isInvalidQuantity(countInput) || (hasRestock && !hasCount));
            });
        });
        document.querySelectorAll("[data-restock-cell]").forEach((cell) => {
            const input = cell.querySelector("[data-restock-input]");
            const invalid = isInvalidQuantity(input);
            cell.classList.toggle("invalid-cell", invalid);
            input?.classList.toggle("invalid", invalid);
        });
    }

    quantityInputs.forEach((input) => input.addEventListener("input", () => {
        updateRequiredCounts();
        renderDirtyState();
    }));

    back.addEventListener("click", (event) => {
        const inputs = changedInputs();
        if (inputs.length === 0) return;
        event.preventDefault();
        changeList.replaceChildren(...limitedChangeItems(inputs, MAX_MODAL_CHANGES));
        modal.classList.remove("hidden");
    });

    document.querySelector("#cancel-tab-switch")?.addEventListener("click", () => {
        modal.classList.add("hidden");
    });

    document.querySelector("#confirm-tab-switch")?.addEventListener("click", () => {
        loadingOverlay?.show({ immediate: true });
        window.location.href = back.href;
    });

    function changeItem(input) {
        const row = document.createElement("div");
        row.className = "change-item";
        row.textContent = `${input.getAttribute("aria-label")}: ${input.dataset.originalValue || "blank"} to ${input.value || "blank"}`;
        return row;
    }

    function limitedChangeItems(inputs, maxVisible) {
        const items = inputs.slice(0, maxVisible).map(changeItem);
        const hiddenCount = inputs.length - items.length;
        if (hiddenCount > 0) {
            const summary = document.createElement("div");
            summary.className = "change-item";
            summary.textContent = `...and ${hiddenCount} more change${hiddenCount === 1 ? "" : "s"}`;
            items.push(summary);
        }
        return items;
    }

    function isInvalidQuantity(input) {
        if (!input || input.value === "") return false;
        return !/^\d+$/.test(input.value);
    }

    updateRequiredCounts();
    renderDirtyState();
});
