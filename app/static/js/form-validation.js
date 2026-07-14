(() => {
    const DIGIT_RULES = new Set(["PIN4", "PIN6", "UPC12"]);
    const PASSWORD_SYMBOL_PATTERN = /[!"#$%&'()*+,\-./:;<=>?@[\\\]^_`{|}~]/;

    function bind(container = document) {
        fields(container).filter(unbound).forEach(bindField);
        groups(container).filter(unbound).forEach(bindGroup);
        forms(container).forEach(bindForm);
    }

    function bindForm(form) {
        form.noValidate = true;
        if (form.dataset.validationSubmit === "manual") return;
        if (form.dataset.validationSubmitBound) return;
        form.dataset.validationSubmitBound = "1";
        form.addEventListener("submit", (event) => validateBeforeSubmit(form, event));
    }

    function bindField(field) {
        field.dataset.validationBound = "1";
        if (DIGIT_RULES.has(field.dataset.validate)) field.addEventListener("input", () => filterDigits(field));
        if (submitOnly(field)) {
            ["change", "input"].forEach((eventName) => field.addEventListener(eventName, () => {
                clearFieldState(field);
                relatedFields(field).forEach(clearFieldState);
            }));
            return;
        }
        const liveEvents = validators(field).includes("image_source") ? ["change"] : ["change", "input"];
        field.addEventListener("blur", () => markTouched(field));
        field.addEventListener("blur", () => validateField(field));
        liveEvents.forEach((eventName) => field.addEventListener(eventName, () => {
            delete field.dataset.externalError;
            validateField(field);
            relatedFields(field).forEach((related) => validateAny(related, { silent: true }));
        }));
        validateField(field, { silent: true });
    }

    function bindGroup(group) {
        group.dataset.validationBound = "1";
        if (submitOnly(group)) {
            groupFields(group).forEach((field) => field.addEventListener("change", () => clearGroupState(group)));
            dependencyTargets(group).forEach((field) => ["change", "input"].forEach((eventName) => field.addEventListener(eventName, () => clearGroupState(group))));
            return;
        }
        groupFields(group).forEach((field) => {
            field.addEventListener("change", () => {
                delete group.dataset.externalError;
                markTouched(group);
                validateGroup(group);
            });
            field.addEventListener("blur", () => markTouched(group));
        });
        dependencyTargets(group).forEach((field) => {
            ["change", "input"].forEach((eventName) => field.addEventListener(eventName, () => validateGroup(group, { silent: true })));
        });
        validateGroup(group, { silent: true });
    }

    function forms(container = document) {
        return [...new Set(nodes(container).map((node) => node.form || node.closest("form")).filter(Boolean))];
    }

    function nodes(container = document) {
        return [...fields(container), ...groups(container)];
    }

    function fields(container = document) {
        return [...container.querySelectorAll("[data-validate]")];
    }

    function groups(container = document) {
        return [...container.querySelectorAll("[data-validate-group]")];
    }

    function groupFields(group) {
        return [...group.querySelectorAll(`input[name="${group.dataset.groupName}"]`)];
    }

    function dependencyTargets(group) {
        return [group.dataset.requiredWhen, group.dataset.skipWhen]
            .filter(Boolean)
            .map((selector) => group.closest("tr, form")?.querySelector(selector))
            .filter(Boolean);
    }

    function unbound(node) {
        return !node.dataset.validationBound;
    }

    async function validateForm(form) {
        const results = await Promise.all(nodes(form).map((node) => validateAny(node, { force: true })));
        const valid = results.every(Boolean);
        if (!valid) focusFirstInvalid(form);
        return valid;
    }

    async function validateBeforeSubmit(form, event, extraCheck = null) {
        if (!hasAsyncValidation(form)) {
            if (extraCheck && !(await extraCheck())) {
                event.preventDefault();
                return false;
            }
            if (validateFormSync(form)) return true;
            event.preventDefault();
            return false;
        }
        if (form.dataset.validationReady === "1") {
            delete form.dataset.validationReady;
            return true;
        }
        event.preventDefault();
        if (extraCheck && !(await extraCheck())) return false;
        if (!(await validateForm(form))) return false;
        form.dataset.validationReady = "1";
        form.requestSubmit(event.submitter || undefined);
        return true;
    }

    function validateFormSync(form) {
        const valid = nodes(form).map((node) => validateAnySync(node, { force: true })).every(Boolean);
        if (!valid) focusFirstInvalid(form);
        return valid;
    }

    function validateAny(node, options = {}) {
        return node.matches("[data-validate-group]") ? validateGroup(node, options) : validateField(node, options);
    }

    function validateAnySync(node, options = {}) {
        return node.matches("[data-validate-group]") ? validateGroup(node, options) : validateFieldSync(node, options);
    }

    async function validateField(field, options = {}) {
        if (field.disabled) return true;
        if (options.force) markTouched(field);
        const message = await fieldError(field);
        renderFieldState(field, message, options);
        return !message;
    }

    function validateFieldSync(field, options = {}) {
        if (field.disabled) return true;
        if (options.force) markTouched(field);
        const message = fieldErrorSync(field);
        renderFieldState(field, message, options);
        return !message;
    }

    function validateGroup(group, options = {}) {
        if (options.force) markTouched(group);
        const message = groupError(group);
        renderGroupState(group, message, options);
        return !message;
    }

    async function fieldError(field) {
        const value = field.value.trim();
        const paired = pairedField(field);
        if (paired && Boolean(value) !== Boolean(paired.value.trim())) return "Enter both quiet hours times.";
        if (!value) return field.required || requiredWhen(field) ? `${label(field)} is required.` : externalError(field);
        if (externalError(field)) return externalError(field);
        for (const validator of validators(field)) {
            const message = await validateRule(validator, field, value);
            if (message) return message;
        }
        return comparisonError(field, value);
    }

    function fieldErrorSync(field) {
        const value = field.value.trim();
        const paired = pairedField(field);
        if (paired && Boolean(value) !== Boolean(paired.value.trim())) return "Enter both quiet hours times.";
        if (!value) return field.required || requiredWhen(field) ? `${label(field)} is required.` : externalError(field);
        if (externalError(field)) return externalError(field);
        for (const validator of validators(field)) {
            const message = validateRule(validator, field, value);
            if (message) return message;
        }
        return comparisonError(field, value);
    }

    function groupError(group) {
        if (skipWhen(group)) return "";
        if (group.dataset.validateGroup === "required_choice" && requiredForGroup(group) && !groupFields(group).some((field) => field.checked)) {
            return `${label(group)} is required.`;
        }
        return externalError(group);
    }

    function validateRule(validator, field, value) {
        if (validator === "email" && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value)) return field.dataset.errorMessage;
        if (validator === "hex_color" && !/^#[0-9A-Fa-f]{6}$/.test(value)) return field.dataset.errorMessage;
        if (validator === "hhmm_time" && !/^([01]\d|2[0-3]):[0-5]\d$/.test(value)) return field.dataset.errorMessage;
        if (validator === "iso_date" && !/^\d{4}-\d{2}-\d{2}$/.test(value)) return field.dataset.errorMessage;
        if (validator === "max_length" && field.dataset.maxLength && value.length > Number(field.dataset.maxLength)) return field.dataset.errorMessage;
        if (validator === "non_negative_int" && (!/^\d+$/.test(value) || Number(value) < 0)) return field.dataset.errorMessage;
        if (validator === "password") return passwordError(value, field);
        if (validator === "pin4" && !/^\d{4}$/.test(value)) return field.dataset.errorMessage;
        if (validator === "pin6" && !/^\d{6}$/.test(value)) return field.dataset.errorMessage;
        if (validator === "positive_int" && (!/^\d+$/.test(value) || Number(value) < 1)) return field.dataset.errorMessage;
        if (validator === "upc12") return upcError(value);
        if (validator === "image_source") return imageSourceError(value, field);
        return "";
    }

    function comparisonError(field, value) {
        if (field.dataset.minDate && value < field.dataset.minDate) return `${label(field)} must be on or after ${field.dataset.minDate}.`;
        if (field.dataset.maxDate && value > field.dataset.maxDate) return `${label(field)} cannot be in the future.`;
        const other = comparisonField(field);
        if (!other || !value || !other.value.trim()) return "";
        if (field.dataset.compareMode === "number_gt" && !(Number(value) > Number(other.value.trim()))) {
            return field.dataset.compareMessage || `${label(field)} must be greater than ${label(other)}.`;
        }
        if (field.dataset.compareMode === "date_gte" && value < other.value.trim()) {
            return field.dataset.compareMessage || `${label(field)} must be on or after ${label(other)}.`;
        }
        return "";
    }

    function isStrongPassword(value, minLength = 10) {
        return value.length >= minLength && /[A-Za-z]/.test(value) && /\d/.test(value) && PASSWORD_SYMBOL_PATTERN.test(value);
    }

    function passwordError(value, field) {
        const minLength = Number(field.dataset.passwordMinLength || 10);
        if (isStrongPassword(value, minLength)) return "";
        const missing = [];
        if (value.length < minLength) missing.push(`${minLength}+ characters`);
        if (!/[A-Za-z]/.test(value)) missing.push("a letter");
        if (!/\d/.test(value)) missing.push("a number");
        if (!PASSWORD_SYMBOL_PATTERN.test(value)) missing.push("a symbol");
        return missing.length ? `Add ${missing.join(", ")}.` : field.dataset.errorMessage;
    }

    function upcError(value) {
        if (!/^\d{12}$/.test(value)) return "UPC must be 12 digits.";
        return upcCheckDigit(value.slice(0, 11)) === value[11] ? "" : "Invalid UPC code.";
    }

    function imageSourceError(value, field) {
        if (!/^https?:\/\//.test(value)) {
            return /\.(gif|jpe?g|png|svg|webp)$/i.test(value) ? "" : field.dataset.errorMessage;
        }
        return new Promise((resolve) => {
            const image = new Image();
            const timeout = window.setTimeout(() => resolve(field.dataset.errorMessage), 4000);
            image.onload = () => {
                window.clearTimeout(timeout);
                resolve("");
            };
            image.onerror = () => {
                window.clearTimeout(timeout);
                resolve(field.dataset.errorMessage);
            };
            image.src = value;
        });
    }

    function filterDigits(field) {
        const filtered = field.value.replace(/\D/g, "").slice(0, Number(field.maxLength || 999));
        if (field.value !== filtered) field.value = filtered;
    }

    function renderFieldState(field, message, { silent = false } = {}) {
        const show = shouldShow(field, message, silent);
        field.dataset.invalidState = message ? "1" : "0";
        field.setCustomValidity(message);
        field.classList.toggle("invalid", show);
        if (field.dataset.validate === "UPC12" && show) pulse(field);
        const hint = ensureHint(field);
        hint.textContent = show ? message : "";
        hint.classList.toggle("hidden", !show);
        field.closest("td")?.classList.toggle("invalid-cell", show);
    }

    function clearFieldState(field) {
        delete field.dataset.touched;
        delete field.dataset.externalError;
        field.dataset.invalidState = "0";
        field.setCustomValidity("");
        field.classList.remove("invalid");
        const hint = field.parentElement?.querySelector(`.field-hint[data-for="${hintKey(field)}"]`);
        if (hint) {
            hint.textContent = "";
            hint.classList.add("hidden");
        }
        field.closest("td")?.classList.remove("invalid-cell");
    }

    function renderGroupState(group, message, { silent = false } = {}) {
        const show = shouldShow(group, message, silent);
        group.dataset.invalidState = message ? "1" : "0";
        invalidTargets(group).forEach((target) => target.classList.toggle("invalid", show));
        const hint = ensureHint(group);
        hint.textContent = show ? message : "";
        hint.classList.toggle("hidden", !show);
    }

    function clearGroupState(group) {
        delete group.dataset.touched;
        delete group.dataset.externalError;
        group.dataset.invalidState = "0";
        invalidTargets(group).forEach((target) => target.classList.remove("invalid"));
        const hint = group.querySelector(`.field-hint[data-for="${hintKey(group)}"]`);
        if (hint) {
            hint.textContent = "";
            hint.classList.add("hidden");
        }
    }

    function shouldShow(node, message, silent) {
        return Boolean(message) && (node.dataset.touched === "1" || !silent);
    }

    function ensureHint(node) {
        const parent = node.matches("[data-validate-group]") ? node : node.parentElement;
        const existing = parent?.querySelector(`.field-hint[data-for="${hintKey(node)}"]`);
        if (existing) return existing;
        const hint = document.createElement("small");
        hint.className = "field-hint hidden";
        hint.dataset.for = hintKey(node);
        if (node.matches("[data-validate-group]")) {
            node.appendChild(hint);
            return hint;
        }
        if (node.matches(".table-input, .small-input, .small-select") || node.parentElement?.matches(".edit-field")) {
            node.insertAdjacentElement("beforebegin", hint);
            return hint;
        }
        node.insertAdjacentElement("afterend", hint);
        return hint;
    }

    function hintKey(node) {
        return node.matches("[data-validate-group]") ? `group:${node.dataset.groupName}` : (node.id || node.name);
    }

    function invalidTargets(group) {
        const selector = group.dataset.invalidSelector || ".choice, .choice-card";
        return [...group.querySelectorAll(selector)];
    }

    function pulse(field) {
        field.classList.remove("validation-pulse");
        field.offsetWidth;
        field.classList.add("validation-pulse");
    }

    function focusFirstInvalid(form) {
        const first = nodes(form).find((node) => node.dataset.invalidState === "1");
        if (!first) return;
        const focusTarget = first.matches("[data-validate-group]") ? groupFields(first)[0] : first;
        focusTarget?.focus();
        focusTarget?.scrollIntoView({ block: "center", behavior: "smooth" });
    }

    function validators(field) {
        return (field.dataset.validators || "").split(",").filter(Boolean);
    }

    function hasAsyncValidation(form) {
        return fields(form).some((field) => validators(field).includes("image_source") && field.value.trim());
    }

    function submitOnly(node) {
        return node.closest("form")?.dataset.validationLive === "submit";
    }

    function relatedFields(field) {
        if (!field.form) return [];
        return fields(field.form).filter((other) => (
            other !== field
            && (other.dataset.pairWith === field.name
                || other.dataset.compareTo === field.name
                || field.dataset.pairWith === other.name
                || field.dataset.compareTo === other.name)
        ));
    }

    function requiredWhen(field) {
        const selector = field.dataset.requiredWhen;
        return Boolean(selector && field.closest("tr, form")?.querySelector(selector)?.value.trim());
    }

    function requiredForGroup(group) {
        const selector = group.dataset.requiredWhen;
        if (!selector) return true;
        return Boolean(group.closest("tr, form")?.querySelector(selector)?.value.trim());
    }

    function skipWhen(group) {
        const selector = group.dataset.skipWhen;
        if (!selector) return false;
        const target = group.closest("tr, form")?.querySelector(selector);
        return Boolean(target?.checked);
    }

    function pairedField(field) {
        return field.dataset.pairWith ? field.form?.querySelector(`[name="${field.dataset.pairWith}"]`) : null;
    }

    function comparisonField(field) {
        return field.dataset.compareTo ? field.form?.querySelector(`[name="${field.dataset.compareTo}"]`) : null;
    }

    function label(field) {
        return field.dataset.label || field.getAttribute("aria-label") || "This field";
    }

    function externalError(node) {
        return node.dataset.externalError || "";
    }

    function markTouched(node) {
        node.dataset.touched = "1";
    }

    function setExternalError(node, message = "") {
        node.dataset.externalError = message;
    }

    function upcCheckDigit(upc11) {
        const total = [...upc11].reduce((sum, digit, index) => sum + Number(digit) * (index % 2 === 0 ? 3 : 1), 0);
        return String((10 - (total % 10)) % 10);
    }

    document.addEventListener("DOMContentLoaded", () => bind());

    window.InventoryFormValidation = {
        bind,
        clearFieldState,
        setExternalError,
        validateBeforeSubmit,
        validateField,
        validateForm,
        validateGroup,
        upcError,
    };
})();
