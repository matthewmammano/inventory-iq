document.addEventListener("DOMContentLoaded", () => {
    function labelTarget(field) {
        const label = field.closest("label");
        if (label) return label.querySelector(":scope > span:first-child") || label;

        if (field.id) {
            const forLabel = document.querySelector(`label[for="${CSS.escape(field.id)}"]`);
            if (forLabel) return forLabel;
        }

        const editField = field.closest(".edit-field");
        if (editField) return editField.querySelector(":scope > span:first-child") || editField;

        const settingRow = field.closest(".setting-row");
        if (settingRow) return settingRow.querySelector(".setting-name");

        return null;
    }

    function mark(target) {
        if (!target || target.querySelector(":scope > .required-marker")) return;
        const marker = document.createElement("span");
        marker.className = "required-marker";
        marker.setAttribute("aria-hidden", "true");
        marker.textContent = " *";
        target.appendChild(marker);
    }

    document.querySelectorAll("[required]").forEach((field) => mark(labelTarget(field)));
    document.querySelectorAll('[data-validate-group="required_choice"]').forEach((group) => mark(labelTarget(group)));
});
