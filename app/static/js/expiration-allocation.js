document.addEventListener("DOMContentLoaded", () => {
    const form = document.querySelector("[data-expiration-form]");
    if (!form) return;

    const groups = [...form.querySelectorAll("[data-expiration-group]")];
    const submit = form.querySelector("[data-exp-submit]");
    const indexToken = "__INDEX__";
    let formComplete = false;
    let submitAttempted = false;

    function quantity(input) {
        const value = Number(input?.value || 0);
        return Number.isFinite(value) && value > 0 ? Math.floor(value) : 0;
    }

    function groupTotal(group) {
        return [...group.querySelectorAll("[data-exp-qty]")].reduce((sum, input) => sum + quantity(input), 0);
    }

    function newRows(group) {
        return [...group.querySelectorAll("[data-exp-new-row]")];
    }

    function rowDateInput(row) {
        return row.querySelector('input[type="date"]');
    }

    function rowQuantityInput(row) {
        return row.querySelector("[data-exp-qty]");
    }

    function rowHasDate(row) {
        return Boolean(rowDateInput(row)?.value);
    }

    function newRowHasValue(row) {
        return rowHasDate(row) || quantity(rowQuantityInput(row)) > 0;
    }

    function maxNewRows(group) {
        return Math.max(0, Number(group.dataset.maxNewRows || 0));
    }

    function nextNewRowIndex(group) {
        return newRows(group).length;
    }

    function renderDateWarning(row) {
        const dateInput = rowDateInput(row);
        const warning = row.querySelector("[data-exp-date-warning]");
        const missingDate = quantity(rowQuantityInput(row)) > 0 && !dateInput?.value;
        row.classList.toggle("expiration-row-invalid", missingDate);
        dateInput?.classList.toggle("invalid", missingDate);
        warning?.classList.toggle("hidden", !missingDate);
        return !missingDate;
    }

    function addNewRow(group) {
        const template = group.querySelector("[data-exp-new-template]");
        if (!template || newRows(group).length >= maxNewRows(group)) return;

        const row = template.content.firstElementChild.cloneNode(true);
        const index = nextNewRowIndex(group);
        row.querySelectorAll("[name], [aria-label]").forEach((element) => {
            if (element.name) element.name = element.name.replace(indexToken, index);
            const label = element.getAttribute("aria-label");
            if (label) element.setAttribute("aria-label", label.replace(indexToken, index));
        });
        template.before(row);
    }

    function reindexNewRows(group) {
        // Field names embed a trailing row index (e.g. exp_new_date_..._2); keep it contiguous
        // with DOM order so a removed row can never leave a later row's index unassigned.
        newRows(group).forEach((row, position) => {
            row.querySelectorAll("[name]").forEach((element) => {
                element.name = element.name.replace(/_\d+$/, `_${position}`);
            });
        });
    }

    function pruneBlankRows(group) {
        // Keep at most one blank row in the whole group (the trailing "add" slot), matching
        // the secondary-UPC dynamic-list behavior: any blank, wherever it is, gets removed.
        const blanks = newRows(group).filter((row) => !newRowHasValue(row));
        if (blanks.length <= 1) return;
        blanks.slice(0, -1).forEach((row) => row.remove());
        reindexNewRows(group);
    }

    function removeBlankRowsWhenAllocated(group) {
        const blanks = newRows(group).filter((row) => !newRowHasValue(row));
        if (blanks.length === 0) return;
        blanks.forEach((row) => row.remove());
        reindexNewRows(group);
    }

    function renderNewRows(group, total, target) {
        let valid = true;
        if (total >= target) {
            removeBlankRowsWhenAllocated(group);
            newRows(group).forEach((row) => {
                valid = renderDateWarning(row) && valid;
            });
            return valid;
        }

        if (newRows(group).length === 0 && maxNewRows(group) > 0) addNewRow(group);
        pruneBlankRows(group);
        const rows = newRows(group);
        const last = rows[rows.length - 1];
        if (last && rowHasDate(last) && total < target && rows.length < maxNewRows(group)) addNewRow(group);

        newRows(group).forEach((row) => {
            valid = renderDateWarning(row) && valid;
        });
        return valid;
    }

    function renderMinusButtons(group) {
        group.querySelectorAll("[data-exp-minus]").forEach((button) => {
            button.disabled = quantity(button.closest(".expiration-stepper")?.querySelector("[data-exp-qty]")) <= 0;
        });
    }

    function setQuantity(input, nextValue) {
        const group = input.closest("[data-expiration-group]");
        const target = Number(group.dataset.target || 0);
        const rowMax = Number(input.dataset.rowMax || target);
        const otherTotal = groupTotal(group) - quantity(input);
        const value = Math.max(0, Math.min(rowMax, target - otherTotal, nextValue));
        input.value = value;
        // A new-date row left with a date but zero quantity submits as an orphaned
        // date/quantity pair the server rejects; clear the date so the row goes fully blank.
        if (value === 0) {
            const dateInput = input.closest("[data-exp-new-row]")?.querySelector('input[type="date"]');
            if (dateInput) dateInput.value = "";
        }
        render();
    }

    function render() {
        let complete = groups.length > 0;
        groups.forEach((group) => {
            const target = Number(group.dataset.target || 0);
            const total = groupTotal(group);
            const totalLabel = group.querySelector("[data-expiration-total]");
            if (totalLabel) totalLabel.textContent = `${total} / ${target}`;
            const rowsValid = renderNewRows(group, total, target);
            const totalMatches = total === target;
            const mismatch = submitAttempted && !totalMatches;
            totalLabel?.classList.toggle("expiration-total-mismatch", mismatch);
            group.classList.toggle("expiration-group-incomplete", mismatch);
            complete = rowsValid && complete && totalMatches;
            renderMinusButtons(group);
            group.querySelectorAll("[data-exp-plus]").forEach((button) => {
                button.disabled = total >= target;
            });
        });
        formComplete = complete;
        submit?.classList.toggle("expiration-submit-blocked", !complete);
        submit?.setAttribute("aria-disabled", complete ? "false" : "true");
    }

    form.addEventListener("click", (event) => {
        const button = event.target.closest("[data-exp-minus], [data-exp-plus]");
        if (!button) return;
        const input = button.closest(".expiration-stepper")?.querySelector("[data-exp-qty]");
        if (!input) return;
        setQuantity(input, quantity(input) + (button.matches("[data-exp-plus]") ? 1 : -1));
    });

    form.addEventListener("input", (event) => {
        if (event.target.matches("[data-exp-qty]")) {
            setQuantity(event.target, quantity(event.target));
            return;
        }
        if (event.target.matches('input[type="date"]')) render();
    });

    form.addEventListener("submit", (event) => {
        render();
        if (formComplete) return;
        event.preventDefault();
        submitAttempted = true;
        render();
        window.InventoryFlash?.show("warning", "Enter expiration dates and quantities until each total is complete.");
    });

    render();
});
