document.addEventListener("DOMContentLoaded", () => {
    const formValidation = window.InventoryFormValidation;

    function inputs(container) {
        return [...container.querySelectorAll("[data-dynamic-input]")];
    }

    function nextId(container) {
        const seq = Number(container.dataset.dynamicSeq || inputs(container).length);
        container.dataset.dynamicSeq = String(seq + 1);
        return `${container.id || "dynamic-field"}-${seq}`;
    }

    function resetClone(input, container) {
        input.id = nextId(container);
        input.value = "";
        input.classList.remove("invalid");
        input.removeAttribute("aria-invalid");
        delete input.dataset.touched;
        delete input.dataset.invalidState;
        delete input.dataset.externalError;
        delete input.dataset.validationBound;
        input.setCustomValidity?.("");
    }

    function syncList(container) {
        const pattern = new RegExp(container.dataset.dynamicPattern);
        let fields = inputs(container);

        // Keep at most one blank field in the whole list (the trailing "add" slot).
        const blanks = fields.filter((field) => !field.value.trim());
        if (blanks.length > 1) {
            blanks.slice(0, -1).forEach((field) => {
                container.querySelector(`.field-hint[data-for="${field.id || field.name}"]`)?.remove();
                field.remove();
            });
            fields = inputs(container);
        }

        const last = fields.at(-1);
        if (last && pattern.test(last.value.trim())) {
            const clone = last.cloneNode(true);
            resetClone(clone, container);
            last.insertAdjacentElement("afterend", clone);
            formValidation?.bind(container);
        }
    }

    document.querySelectorAll("[data-dynamic-list]").forEach((container) => {
        container.addEventListener("input", (event) => {
            if (event.target.matches("[data-dynamic-input]")) syncList(container);
        });
    });
});
