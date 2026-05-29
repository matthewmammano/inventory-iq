document.addEventListener("DOMContentLoaded", () => {
    const MAX_MODAL_CHANGES = 5;
    const fields = [...document.querySelectorAll("[data-label]")];
    const form = document.querySelector("#settings-form");
    const saveButton = document.querySelector("#save-button");
    const backLink = document.querySelector("#back-link");
    const modal = document.querySelector("#confirm-modal");
    if (!fields.length || !form || !saveButton || !backLink || !modal) return;

    const modalTitle = document.querySelector("#modal-title");
    const modalMessage = document.querySelector("#modal-message");
    const changeList = document.querySelector("#change-list");
    const confirmButton = document.querySelector("#confirm-button");
    let modalMode = "save";

    const valueOf = (field) => field.classList.contains("switch") ? field.textContent.trim() : field.value;
    const displayOf = (field) => field.tagName === "SELECT"
        ? field.selectedOptions[0]?.textContent.trim()
        : valueOf(field);
    const displayValue = (value) => value || "Not selected";
    const changes = () => fields
        .map((field) => ({
            label: field.dataset.label,
            from: field.dataset.originalDisplay || displayValue(field.dataset.original),
            to: displayValue(displayOf(field)),
            changed: field.dataset.original !== valueOf(field),
        }))
        .filter((change) => change.changed);
    const invalidFields = () => fields.filter((field) => !field.checkValidity());

    function renderDirtyState() {
        const pending = changes();
        saveButton.classList.toggle("hidden", pending.length === 0);
        fields.forEach((field) => field.classList.toggle("changed", field.dataset.original !== valueOf(field)));
        fields.forEach((field) => field.classList.toggle("invalid", !field.checkValidity()));
    }

    function openModal(mode) {
        const pending = changes();
        if (pending.length === 0) return;
        const invalid = invalidFields();
        if (invalid.length) {
            invalid.forEach((field) => field.classList.add("invalid"));
            invalid[0].focus();
            return;
        }
        if (!form.checkValidity()) {
            form.reportValidity();
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
        changeList.replaceChildren(...limitedChangeItems(pending, MAX_MODAL_CHANGES));
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

function changeItem(change) {
    const item = document.createElement("div");
    item.className = "change-item";
    item.textContent = `${change.label}: ${change.from} to ${change.to}`;
    return item;
}

function limitedChangeItems(changes, maxVisible) {
    const items = changes.slice(0, maxVisible).map(changeItem);
    const hiddenCount = changes.length - items.length;
    if (hiddenCount > 0) {
        const summary = document.createElement("div");
        summary.className = "change-item";
        summary.textContent = `...and ${hiddenCount} more change${hiddenCount === 1 ? "" : "s"}`;
        items.push(summary);
    }
    return items;
}
