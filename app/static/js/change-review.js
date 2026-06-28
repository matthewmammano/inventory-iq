(() => {
    const CHECKBOX_TRUE_VALUES = new Set(["Yes", "Selected", "Delete", "On"]);

    function truncateValue(value) {
        return value.length > 20 ? `${value.slice(0, 20)}...` : value;
    }

    function renderTextValue(value) {
        const textValue = String(value ?? "");
        const text = document.createElement("span");
        text.className = "change-item-value";
        text.textContent = truncateValue(textValue);
        text.title = textValue;
        return text;
    }

    function renderCheckboxValue(value) {
        const checked = CHECKBOX_TRUE_VALUES.has(String(value ?? ""));
        const checkbox = document.createElement("span");
        checkbox.className = "change-item-checkbox";
        checkbox.classList.toggle("is-checked", checked);
        checkbox.setAttribute("role", "img");
        checkbox.setAttribute("aria-label", checked ? "Checked" : "Unchecked");
        checkbox.title = checked ? "Checked" : "Unchecked";
        return checkbox;
    }

    function renderChangeValue(change, value) {
        return change.kind === "boolean" ? renderCheckboxValue(value) : renderTextValue(value);
    }

    function renderChangeItem(change) {
        const item = document.createElement("div");
        item.className = "change-item";

        const label = document.createElement("span");
        label.className = "change-item-label";
        label.textContent = `${change.label}:`;

        const arrow = document.createElement("span");
        arrow.className = "change-item-arrow";
        arrow.textContent = "->";

        item.append(label, renderChangeValue(change, change.from), arrow, renderChangeValue(change, change.to));
        return item;
    }

    function renderGroupedItems(changes, groupLabel) {
        const groups = new Map();

        changes.forEach((change) => {
            const label = groupLabel(change) || "Changes";
            if (!groups.has(label)) groups.set(label, []);
            groups.get(label).push(change);
        });

        return [...groups.entries()].map(([label, groupChanges]) => {
            const group = document.createElement("section");
            group.className = "change-record";

            const heading = document.createElement("h3");
            heading.className = "change-record-title";
            heading.textContent = label;

            const items = document.createElement("div");
            items.className = "change-record-items";
            items.append(...groupChanges.map(renderChangeItem));

            group.append(heading, items);
            return group;
        });
    }

    window.InventoryChangeReview = {
        renderChangeItem,
        renderGroupedItems,
    };
})();
