document.addEventListener("DOMContentLoaded", () => {
    const form = document.querySelector("[data-bulk-item-select]");
    if (!form) return;

    const search = form.querySelector("#bulk-item-search");
    const rows = [...form.querySelectorAll("[data-item-row]")];
    const boxes = [...form.querySelectorAll("input[name='item_ids']")];
    const selectAll = form.querySelector("[data-select-all]");
    const button = form.querySelector("[data-continue]");
    const count = form.querySelector("[data-selected-count]");

    const visibleRows = () => rows.filter((row) => !row.hidden);

    function update() {
        const selected = boxes.filter((box) => box.checked).length;
        count.textContent = `${selected} item${selected === 1 ? "" : "s"} selected`;
        button.disabled = selected === 0;
    }

    search.addEventListener("input", () => {
        const query = search.value.trim().toLowerCase();
        rows.forEach((row) => {
            row.hidden = Boolean(query && !row.dataset.search.includes(query));
        });
        const visible = visibleRows();
        selectAll.checked = visible.length > 0
            && visible.every((row) => row.querySelector("input").checked);
    });

    selectAll.addEventListener("change", () => {
        visibleRows().forEach((row) => {
            row.querySelector("input").checked = selectAll.checked;
        });
        update();
    });

    boxes.forEach((box) => box.addEventListener("change", update));
    update();
});
