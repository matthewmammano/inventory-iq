document.addEventListener("DOMContentLoaded", () => {
    const MAX_MODAL_CHANGES = 5;
    const modal = document.querySelector("#tab-confirm-modal");
    const changeList = document.querySelector("#tab-change-list");
    const back = document.querySelector("[data-bulk-back]");
    if (!modal || !changeList || !back) return;

    const requiredCells = [...document.querySelectorAll("[data-count-required='1']")];
    const changedInputs = () => [...document.querySelectorAll("[data-original-value]")]
        .filter((input) => input.value !== input.dataset.originalValue);

    function updateRequiredCounts() {
        document.querySelectorAll("tbody tr").forEach((row) => {
            const rowRequiresCounts = [...row.querySelectorAll("[data-count-required='1']")];
            const hasRestock = [...row.querySelectorAll("[data-restock-input]")]
                .some((input) => Number(input.value || 0) > 0);
            rowRequiresCounts.forEach((cell) => {
                const countInput = cell.querySelector("[data-count-input]");
                const hasCount = Boolean(countInput && countInput.value !== "");
                cell.classList.toggle("invalid-cell", hasRestock && !hasCount);
            });
        });
    }

    requiredCells.forEach((cell) => {
        cell.querySelector("[data-count-input]")?.addEventListener("input", updateRequiredCounts);
        cell.nextElementSibling
            ?.querySelector("[data-restock-input]")
            ?.addEventListener("input", updateRequiredCounts);
    });

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

    updateRequiredCounts();
});
