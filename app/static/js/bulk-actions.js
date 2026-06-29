document.addEventListener("DOMContentLoaded", () => {
    const changeReview = window.InventoryChangeReview;
    const form = document.querySelector("#bulk-action-form");
    const saveButton = document.querySelector("#bulk-save-button");
    const submitButton = document.querySelector("#bulk-submit-button");
    const back = document.querySelector("[data-bulk-back]");
    const modal = document.querySelector("#bulk-confirm-modal");
    const changeList = document.querySelector("#bulk-change-list");
    const modalTitle = document.querySelector("#bulk-modal-title");
    const modalMessage = document.querySelector("#bulk-modal-message");
    const confirmButton = document.querySelector("#bulk-confirm-button");
    const cancelButton = document.querySelector("#bulk-cancel-button");
    const loadingOverlay = window.InventoryLoadingOverlay;
    const formValidation = window.InventoryFormValidation;
    let modalMode = "save";
    if (!changeReview || !form || !saveButton || !submitButton || !back || !modal || !changeList || !modalTitle || !modalMessage || !confirmButton || !cancelButton || !formValidation) return;

    const quantityInputs = [...document.querySelectorAll("[data-count-input], [data-restock-input]")];
    const changedInputs = () => [...document.querySelectorAll("[data-original-value]")]
        .filter((input) => input.value !== input.dataset.originalValue);
    const rowLabel = (input) => input.closest("tr")?.querySelector("th")?.textContent.trim() || "Changes";
    const fieldLabel = (input) => input.dataset.label.replace(`${rowLabel(input)} `, "").replace(/^count\b/, "COUNT").replace(/^restock\b/, "RESTOCK");
    const changes = () => changedInputs().map((input) => ({
        kind: "text",
        label: fieldLabel(input),
        from: input.dataset.originalValue || "blank",
        to: input.value || "blank",
        input,
    }));

    function updateRequiredCounts() {
        document.querySelectorAll("tbody tr").forEach((row) => {
            const rowRequiresCounts = [...row.querySelectorAll("[data-count-required='1']")];
            const hasRestock = [...row.querySelectorAll("[data-restock-input]")]
                .some((input) => Number(input.value || 0) > 0);
            rowRequiresCounts.forEach((cell) => {
                const countInput = cell.querySelector("[data-count-input]");
                const hasCount = Boolean(countInput && countInput.value !== "");
                const staleHint = cell.querySelector("[data-count-stale]");
                if (!countInput) return;
                staleHint?.classList.toggle("hidden", hasCount || hasRestock);
                formValidation.setExternalError(countInput, hasRestock && !hasCount ? "Count required if restocking." : "");
                formValidation.validateField(countInput);
            });
        });
    }

    function renderDirtyState() {
        const dirty = changedInputs().length > 0;
        saveButton.classList.toggle("hidden", !dirty);
    }

    async function openModal(mode) {
        const pending = changes();
        if (pending.length === 0) return false;
        updateRequiredCounts();
        if (mode === "save" && !(await formValidation.validateForm(form))) return true;
        modalMode = mode;
        modalTitle.textContent = mode === "save" ? "Review Changes" : "Unsaved Changes";
        modalMessage.textContent = mode === "save"
            ? "Confirm these bulk changes before saving."
            : "Leave without saving these bulk changes?";
        confirmButton.textContent = mode === "save" ? "Yes, Save" : "Leave Without Saving";
        confirmButton.classList.toggle("success-button", mode === "save");
        confirmButton.classList.toggle("danger-button", mode !== "save");
        changeList.replaceChildren(...changeReview.renderGroupedItems(pending, (change) => rowLabel(change.input)));
        modal.classList.remove("hidden");
        return true;
    }

    quantityInputs.forEach((input) => input.addEventListener("input", () => {
        updateRequiredCounts();
        renderDirtyState();
    }));

    form.addEventListener("submit", updateRequiredCounts, { capture: true });

    saveButton.addEventListener("click", () => openModal("save"));
    back.addEventListener("click", (event) => {
        if (changedInputs().length === 0) return;
        event.preventDefault();
        openModal("back");
    });

    cancelButton.addEventListener("click", () => {
        modal.classList.add("hidden");
    });

    confirmButton.addEventListener("click", () => {
        if (modalMode === "save") {
            form.requestSubmit(submitButton);
            return;
        }
        loadingOverlay?.show({ immediate: true });
        window.location.href = back.href;
    });
    updateRequiredCounts();
    renderDirtyState();
});
