document.addEventListener("DOMContentLoaded", () => {
    const changeReview = window.InventoryChangeReview;
    const formValidation = window.InventoryFormValidation;
    const fields = [...document.querySelectorAll("[data-label]")];
    const form = document.querySelector("#settings-form");
    const saveButton = document.querySelector("#save-button");
    const backLink = document.querySelector("#back-link");
    const modal = document.querySelector("#confirm-modal");
    if (!changeReview || !formValidation || !fields.length || !form || !saveButton || !backLink || !modal) return;

    const modalTitle = document.querySelector("#modal-title");
    const modalMessage = document.querySelector("#modal-message");
    const changeList = document.querySelector("#change-list");
    const confirmButton = document.querySelector("#confirm-button");
    const loadingOverlay = window.InventoryLoadingOverlay;
    let modalMode = "save";

    const valueOf = (field) => field.classList.contains("switch") ? field.textContent.trim() : field.value;
    const displayOf = (field) => field.tagName === "SELECT"
        ? field.selectedOptions[0]?.textContent.trim()
        : valueOf(field);
    const displayValue = (value) => value || "Empty";
    const changes = () => fields
        .map((field) => ({
            kind: field.classList.contains("switch") ? "boolean" : "text",
            label: field.dataset.label,
            from: field.dataset.originalDisplay || displayValue(field.dataset.original),
            to: displayValue(displayOf(field)),
            changed: field.dataset.original !== valueOf(field),
        }))
        .filter((change) => change.changed);
    function renderDirtyState() {
        const pending = changes();
        saveButton.classList.toggle("hidden", pending.length === 0);
        fields.forEach((field) => field.classList.toggle("changed", field.dataset.original !== valueOf(field)));
    }

    async function openModal(mode) {
        const pending = changes();
        if (pending.length === 0) return;
        if (mode !== "back" && !(await formValidation.validateForm(form))) {
            return;
        }
        modalMode = mode;
        modalTitle.textContent = mode === "back" ? "Unsaved Changes" : "Review Changes";
        modalMessage.textContent = mode === "back"
            ? "You have unsaved changes. Leave without saving?"
            : "Confirm these settings before saving.";
        confirmButton.textContent = mode === "back" ? "Leave Without Saving" : "Yes, Save";
        confirmButton.classList.toggle("danger-button", mode === "back");
        confirmButton.classList.toggle("success-button", mode !== "back");
        changeList.replaceChildren(...pending.map(changeReview.renderChangeItem));
        modal.classList.remove("hidden");
    }

    fields.forEach((field) => bindField(field, renderDirtyState));
    saveButton.addEventListener("click", () => openModal("save"));
    backLink.addEventListener("click", (event) => {
        if (changes().length === 0) return;
        event.preventDefault();
        openModal("back");
    });
    document.querySelector("#cancel-modal").addEventListener("click", () => modal.classList.add("hidden"));
    confirmButton.addEventListener("click", () => {
        if (modalMode === "back") {
            loadingOverlay?.show({ immediate: true });
            window.location.href = backLink.href;
            return;
        }
        form.requestSubmit();
    });
});

function bindField(field, renderDirtyState) {
    field.addEventListener("change", renderDirtyState);
    field.addEventListener("input", renderDirtyState);
    if (!field.classList.contains("switch")) return;
    field.addEventListener("click", () => {
        field.textContent = field.textContent.trim() === "On" ? "Off" : "On";
        field.classList.toggle("off", field.textContent.trim() === "Off");
        const input = document.querySelector(`input[name="${field.dataset.input}"]`);
        if (input) input.value = field.textContent.trim() === "On" ? "1" : "0";
        renderDirtyState();
    });
}
