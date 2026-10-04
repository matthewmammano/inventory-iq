document.addEventListener("DOMContentLoaded", () => {
    const form = document.querySelector("[data-expiration-form]");
    if (!form) return;

    const groups = [...form.querySelectorAll("[data-expiration-group]")];
    const submit = form.querySelector("[data-exp-submit]");
    const indexToken = "__INDEX__";
    let formComplete = false;
    let submitAttempted = false;

    function requiresExactTotal(group) {
        return group.dataset.requiresExact === "1";
    }

    function qtyInput(qtyEl) {
        return qtyEl?.closest(".expiration-stepper")?.querySelector("[data-exp-qty-input]") ?? qtyEl;
    }

    function quantity(qtyEl) {
        const value = Number(qtyInput(qtyEl)?.value || 0);
        return Number.isFinite(value) && value > 0 ? Math.floor(value) : 0;
    }

    function groupTotal(group) {
        return [...group.querySelectorAll("[data-exp-qty]")].reduce((sum, qtyEl) => sum + quantity(qtyEl), 0);
    }

    function newRows(group) {
        return [...group.querySelectorAll("[data-exp-new-row]")];
    }

    function rowDateInput(row) {
        return row.querySelector('input[type="date"]');
    }

    function rowQuantityEl(row) {
        return row.querySelector("[data-exp-qty]");
    }

    function rowHasDate(row) {
        return Boolean(rowDateInput(row)?.value);
    }

    function newRowHasValue(row) {
        return rowHasDate(row) || quantity(rowQuantityEl(row)) > 0;
    }

    function maxNewRows(group) {
        return Math.max(0, Number(group.dataset.maxNewRows || 0));
    }

    function nextNewRowIndex(group) {
        return newRows(group).length;
    }

    function syncStepperVisibility(row) {
        const stepper = row.querySelector(".expiration-stepper");
        if (stepper) stepper.hidden = !rowHasDate(row);
    }

    function renderDateWarning(row) {
        const dateInput = rowDateInput(row);
        const warning = row.querySelector("[data-exp-date-warning]");
        const missingDate = quantity(rowQuantityEl(row)) > 0 && !dateInput?.value;
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
        const requiresExact = requiresExactTotal(group);
        if (requiresExact && total >= target) {
            removeBlankRowsWhenAllocated(group);
            newRows(group).forEach((row) => {
                syncStepperVisibility(row);
                valid = renderDateWarning(row) && valid;
            });
            return valid;
        }

        if (newRows(group).length === 0 && maxNewRows(group) > 0) addNewRow(group);
        pruneBlankRows(group);
        const rows = newRows(group);
        const last = rows[rows.length - 1];
        const stillGrowing = !requiresExact || total < target;
        if (last && rowHasDate(last) && stillGrowing && rows.length < maxNewRows(group)) addNewRow(group);

        newRows(group).forEach((row) => {
            syncStepperVisibility(row);
            valid = renderDateWarning(row) && valid;
        });
        return valid;
    }

    function renderOtherHighlight(group) {
        const otherRow = group.querySelector("[data-exp-other-row]");
        const otherQty = otherRow?.querySelector("[data-exp-qty]");
        if (!otherRow || !otherQty) return;
        const discouraged = otherRow.dataset.expOtherDiscouraged === "1";
        otherRow.classList.toggle("expiration-other-used", discouraged && quantity(otherQty) > 0);
    }

    function renderMinusButtons(group) {
        group.querySelectorAll("[data-exp-minus]").forEach((button) => {
            button.disabled = quantity(button.closest(".expiration-stepper")?.querySelector("[data-exp-qty]")) <= 0;
        });
    }

    function updateProgress(group, total, target) {
        const progress = group.querySelector("[data-expiration-total]");
        if (!progress) return;
        const label = progress.querySelector(".expiration-progress-label");
        if (label) label.textContent = `${total} / ${target}`;
        const fill = progress.querySelector(".expiration-progress-fill");
        if (fill) fill.style.width = `${target > 0 ? Math.min(100, (total / target) * 100) : 0}%`;
        progress.classList.toggle("expiration-is-complete", target > 0 && total === target);
        progress.classList.toggle("expiration-is-over", total > target);
    }

    function setQuantity(qtyEl, nextValue) {
        const group = qtyEl.closest("[data-expiration-group]");
        const target = Number(group.dataset.target || 0);
        const rowMax = Number(qtyEl.dataset.rowMax || target);
        const otherTotal = groupTotal(group) - quantity(qtyEl);
        const cap = requiresExactTotal(group) ? Math.min(rowMax, target - otherTotal) : rowMax;
        const value = Math.max(0, Math.min(cap, nextValue));
        const input = qtyInput(qtyEl);
        input.value = value;
        qtyEl.textContent = value;
        // A new-date row left with a date but zero quantity submits as an orphaned
        // date/quantity pair the server rejects; clear the date so the row goes fully blank.
        if (value === 0) {
            const dateInput = qtyEl.closest("[data-exp-new-row]")?.querySelector('input[type="date"]');
            if (dateInput) dateInput.value = "";
        }
        render();
    }

    function render() {
        let complete = groups.length > 0;
        groups.forEach((group) => {
            const target = Number(group.dataset.target || 0);
            const total = groupTotal(group);
            const requiresExact = requiresExactTotal(group);
            updateProgress(group, total, target);
            const rowsValid = renderNewRows(group, total, target);
            const totalMatches = requiresExact ? total === target : total > 0;
            const mismatch = submitAttempted && !totalMatches;
            group.classList.toggle("expiration-group-incomplete", mismatch);
            complete = rowsValid && complete && totalMatches;
            renderOtherHighlight(group);
            renderMinusButtons(group);
            group.querySelectorAll("[data-exp-plus]").forEach((button) => {
                button.disabled = requiresExact && total >= target;
            });
        });
        formComplete = complete;
        submit?.classList.toggle("expiration-submit-blocked", !complete);
        submit?.setAttribute("aria-disabled", complete ? "false" : "true");
    }

    form.addEventListener("click", (event) => {
        const otherToggle = event.target.closest("[data-exp-other-toggle]");
        if (otherToggle) {
            otherToggle.closest(".expiration-card-body")?.querySelector("[data-exp-other-row]")?.classList.remove("hidden");
            otherToggle.remove();
            return;
        }
        const button = event.target.closest("[data-exp-minus], [data-exp-plus]");
        if (!button) return;
        const qtyEl = button.closest(".expiration-stepper")?.querySelector("[data-exp-qty]");
        if (!qtyEl) return;
        setQuantity(qtyEl, quantity(qtyEl) + (button.matches("[data-exp-plus]") ? 1 : -1));
    });

    form.addEventListener("input", (event) => {
        if (!event.target.matches('input[type="date"]')) return;
        if (!event.target.value) {
            const qtyEl = event.target.closest("[data-exp-new-row]")?.querySelector("[data-exp-qty]");
            if (qtyEl) setQuantity(qtyEl, 0);
            return;
        }
        render();
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
