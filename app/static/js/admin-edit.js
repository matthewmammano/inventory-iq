document.addEventListener("DOMContentLoaded", () => {
    const changeReview = window.InventoryChangeReview;
    const formValidation = window.InventoryFormValidation;
    const saveButton = document.querySelector("#edit-save-button");
    const backLink = document.querySelector("#edit-back-link");
    const modal = document.querySelector("#edit-confirm-modal");
    const changeList = document.querySelector("#edit-change-list");
    const confirmButton = document.querySelector("#edit-confirm-button");
    const cancelButton = document.querySelector("#edit-cancel-button");
    const modalTitle = document.querySelector("#edit-modal-title");
    const modalMessage = document.querySelector("#edit-modal-message");
    const loadingOverlay = window.InventoryLoadingOverlay;
    let modalMode = "save";
    let pendingTab = null;

    if (!changeReview || !formValidation || !saveButton || !backLink || !modal || !changeList || !confirmButton || !cancelButton) return;

    const panels = () => [...document.querySelectorAll(".tab-panel")];
    const activePanel = () => panels().find((panel) => !panel.classList.contains("hidden"));
    const activeForm = () => activePanel()?.querySelector("[data-edit-form]");
    const fields = (form) => [...(form || document).querySelectorAll("input[data-label], select[data-label], textarea[data-label]")];
    const comparableValue = (field, value) => {
        if (field.type === "number" && value !== "") return String(Number(value));
        if (field.type === "color") return value.toUpperCase();
        return value;
    };
    const checkboxDisplay = (field, checked) => field.dataset[checked ? "onDisplay" : "offDisplay"] || (checked ? "Yes" : "No");
    const isInactiveNewNotificationField = (field) => {
        const row = field.closest("[data-new-email-row]");
        if (!row) return false;
        const emailInput = row.querySelector("input[type='email']");
        return !emailInput?.value.trim();
    };
    const valueOf = (field) => {
        if (field.type === "checkbox") return field.checked ? "1" : "0";
        return comparableValue(field, field.value);
    };
    const displayOf = (field) => {
        if (field.type === "checkbox") return checkboxDisplay(field, field.checked);
        if (field.tagName === "SELECT") return field.selectedOptions[0]?.textContent.trim() || field.value;
        if (field.type === "color") return field.value.toUpperCase();
        return field.value || "Empty";
    };
    const originalDisplayOf = (field) => {
        if (field.dataset.originalDisplay) return field.dataset.originalDisplay;
        if (field.type === "checkbox") return checkboxDisplay(field, field.dataset.original === "1");
        if (field.tagName === "SELECT") return field.querySelector(`option[value="${field.dataset.original}"]`)?.textContent.trim() || field.dataset.original;
        if (field.type === "color") return (field.dataset.original || "").toUpperCase();
        return field.dataset.original || "Empty";
    };
    const changes = (form = activeForm()) => fields(form)
        .filter((field) => !isInactiveNewNotificationField(field))
        .map((field) => ({
            field,
            kind: field.type === "checkbox" ? "boolean" : "text",
            label: field.dataset.label,
            from: originalDisplayOf(field),
            to: displayOf(field),
            changed: valueOf(field) !== comparableValue(field, field.dataset.original || ""),
        }))
        .filter((change) => change.changed);
    const isCompleteUpc = (value) => /^\d{12}$/.test(value);
    const bindDirtyFields = (container = document) => fields(container)
        .filter((field) => !field.dataset.dirtyBound)
        .forEach((field) => {
            field.dataset.dirtyBound = "1";
            ["change", "input"].forEach((eventName) => field.addEventListener(eventName, renderDirtyState));
        });

    function clearDeletedUpcs(form) {
        form?.querySelectorAll("[data-clear-field]:checked").forEach((checkbox) => {
            const input = checkbox.closest(".upc-edit-row")?.querySelector("input[name$='_secondary_upcs']");
            if (input) input.value = "";
        });
    }

    function resetForm(form) {
        form?.querySelectorAll("[data-added-row]").forEach((row) => row.remove());
        fields(form).forEach((field) => {
            if (field.type === "checkbox") {
                field.checked = field.dataset.original === "1";
            } else {
                field.value = field.dataset.original || "";
            }
        });
        resetValidationState(form);
        formValidation.bind(form);
    }

    function bindDynamicRows(container = document) {
        container.querySelectorAll("[data-upc-add-input]:not([data-dynamic-bound])").forEach((input) => {
            input.dataset.dynamicBound = "1";
            input.addEventListener("input", () => {
                syncAddUpcRows(input);
            });
        });
        container.querySelectorAll("[data-new-email-row]:not([data-dynamic-bound])").forEach((row) => {
            row.dataset.dynamicBound = "1";
            row.querySelector("input[type='email']")?.addEventListener("input", (event) => {
                formValidation.validateField(event.target).then((valid) => {
                    if (valid && !row.nextElementSibling?.matches("[data-new-email-row]")) {
                        addBlankEmailRow(row);
                    }
                });
            });
        });
        formValidation.bind(container);
    }

    function resetValidationState(container) {
        container.querySelectorAll(".field-hint").forEach((hint) => hint.remove());
        container.querySelectorAll("[data-validate]").forEach((field) => {
            delete field.dataset.touched;
            delete field.dataset.validationBound;
            delete field.dataset.invalidState;
            delete field.dataset.externalError;
            field.classList.remove("invalid");
            field.closest("td")?.classList.remove("invalid-cell");
            field.setCustomValidity("");
        });
    }

    function renderDirtyState() {
        const form = activeForm();
        const dirty = changes(form).length > 0;
        saveButton.classList.toggle("hidden", !dirty);
        saveButton.setAttribute("form", form?.id || "");
        fields().forEach((field) => {
            field.classList.toggle("changed", valueOf(field) !== comparableValue(field, field.dataset.original || ""));
        });
    }

    async function openModal(mode, nextTab = null) {
        const form = activeForm();
        const source = mode === "back" ? document : form;
        const pending = changes(source);
        if (!form || pending.length === 0) return false;
        if (mode === "save" && !(await formValidation.validateForm(form))) {
            return true;
        }
        modalMode = mode;
        pendingTab = nextTab;
        modalTitle.textContent = mode === "save" ? "Review Changes" : "Unsaved Changes";
        modalMessage.textContent = mode === "save" ? "Confirm these changes before saving." : "Leave without saving these changes?";
        confirmButton.textContent = mode === "save" ? "Yes, Save" : "Leave Without Saving";
        confirmButton.classList.toggle("danger-button", mode !== "save");
        confirmButton.classList.toggle("success-button", mode === "save");
        changeList.replaceChildren(...changeReview.renderGroupedItems(pending, (change) => rowLabel(change.field)));
        modal.classList.remove("hidden");
        return true;
    }

    function showTab(tabName) {
        document.querySelectorAll("[data-tab]").forEach((tab) => tab.classList.toggle("active", tab.dataset.tab === tabName));
        panels().forEach((panel) => panel.classList.toggle("hidden", panel.id !== tabName));
        renderDirtyState();
    }

    function addBlankUpcRow(input) {
        const row = input.closest("[data-upc-add-row]");
        const clone = row.cloneNode(true);
        const cloneInput = clone.querySelector("input");
        cloneInput.value = "";
        cloneInput.dataset.original = "";
        delete cloneInput.dataset.dynamicBound;
        clone.dataset.addedRow = "1";
        resetValidationState(clone);
        row.after(clone);
        bindDirtyFields(clone);
        bindDynamicRows(clone);
    }

    function syncAddUpcRows(input) {
        const currentRow = input.closest("[data-upc-add-row]");
        const rows = () => [...input.closest("td")?.querySelectorAll("[data-upc-add-row]") || []];
        const emptyRows = rows().filter((row) => !row.querySelector("[data-upc-add-input]")?.value.trim());
        if (!input.value.trim() && currentRow?.dataset.addedRow && emptyRows.length > 1) {
            currentRow.remove();
            renderDirtyState();
            return;
        }
        emptyRows.slice(1).filter((row) => row.dataset.addedRow).forEach((row) => row.remove());
        const addRows = rows();
        if (addRows.length > 0 && addRows.every((row) => isCompleteUpc(row.querySelector("[data-upc-add-input]").value.trim()))) {
            addBlankUpcRow(addRows.at(-1).querySelector("[data-upc-add-input]"));
        }
    }

    function addBlankEmailRow(row) {
        const clone = row.cloneNode(true);
        const nextIndex = Math.max(...[...document.querySelectorAll("[data-new-email-row]")].map((item) => Number(item.dataset.emailIndex || 0))) + 1;
        const oldPrefix = `new_email_${row.dataset.emailIndex || 0}`;
        const newPrefix = `new_email_${nextIndex}`;
        clone.dataset.emailIndex = String(nextIndex);
        clone.dataset.addedRow = "1";
        clone.querySelector("input[name='new_email_keys']").value = newPrefix;
        clone.querySelectorAll("[name]").forEach((field) => {
            field.name = field.name.replace(oldPrefix, newPrefix);
            if (field.dataset.pairWith) field.dataset.pairWith = field.dataset.pairWith.replace(oldPrefix, newPrefix);
        });
        clone.querySelectorAll("[data-validate-group]").forEach((group) => {
            if (group.dataset.groupName) group.dataset.groupName = group.dataset.groupName.replace(oldPrefix, newPrefix);
        });
        clone.querySelectorAll("input").forEach((input) => {
            input.checked = false;
            if (input.type !== "hidden" && input.type !== "checkbox") input.value = "";
            input.dataset.original = input.type === "checkbox" ? "0" : "";
            delete input.dataset.dirtyBound;
        });
        clone.querySelectorAll("select").forEach((select) => {
            select.value = select.dataset.original || "";
            delete select.dataset.dirtyBound;
        });
        delete clone.dataset.dynamicBound;
        resetValidationState(clone);
        row.after(clone);
        bindDirtyFields(clone);
        bindDynamicRows(clone);
    }

    document.querySelectorAll("[data-tab]").forEach((tab) => {
        tab.addEventListener("click", (event) => {
            event.preventDefault();
            if (tab.classList.contains("active")) return;
            openModal("tab", tab.dataset.tab).then((opened) => {
                if (!opened) showTab(tab.dataset.tab);
            });
        });
    });
    bindDirtyFields();
    bindDynamicRows();
    saveButton.addEventListener("click", () => openModal("save"));
    backLink.addEventListener("click", (event) => {
        if (changes(document).length === 0) return;
        event.preventDefault();
        openModal("back");
    });
    cancelButton.addEventListener("click", () => modal.classList.add("hidden"));
    confirmButton.addEventListener("click", () => {
        if (modalMode === "save") {
            clearDeletedUpcs(activeForm());
            activeForm()?.requestSubmit();
            return;
        }
        modal.classList.add("hidden");
        if (modalMode === "tab" && pendingTab) {
            resetForm(activeForm());
            showTab(pendingTab);
        }
        if (modalMode === "back") {
            loadingOverlay?.show({ immediate: true });
            window.location.href = backLink.href;
        }
    });
    renderDirtyState();
});

function rowLabel(field) {
    const row = field.closest("tr");
    const typed = row?.querySelector("input[name$='_name'], input[type='email']")?.value.trim();
    const label = row?.dataset.rowLabel || row?.querySelector("th")?.textContent.trim() || "";
    return typed && label.startsWith("New ") ? typed : label;
}
