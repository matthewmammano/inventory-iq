document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll("[data-sort-table]").forEach((table) => {
        const headers = [...table.querySelectorAll("th[data-sort-column]")];
        const tbody = table.tBodies[0];
        if (!tbody) return;

        const sortRows = (column, direction) => {
            const rows = [...tbody.rows];
            const multiplier = direction === "asc" ? 1 : -1;
            rows.sort((left, right) => multiplier * compareCells(left.cells[column], right.cells[column]));
            tbody.replaceChildren(...rows);
            headers.forEach((header) => header.classList.toggle("sorted-column", Number(header.dataset.sortColumn) === column));
            table.querySelectorAll("td.sorted-cell").forEach((cell) => cell.classList.remove("sorted-cell"));
            [...tbody.rows].forEach((row) => row.cells[column]?.classList.add("sorted-cell"));
            table.dataset.sortDirection = direction;
            table.dataset.sortColumn = column;
        };

        headers.forEach((header) => {
            header.addEventListener("click", (event) => {
                if (event.target.closest("button")) return;
                const column = Number(header.dataset.sortColumn);
                const nextDirection = table.dataset.sortColumn === String(column) && table.dataset.sortDirection === "asc" ? "desc" : "asc";
                sortRows(column, nextDirection);
            });
        });

        const defaultColumn = Number(table.dataset.defaultSortColumn);
        if (Number.isInteger(defaultColumn)) sortRows(defaultColumn, table.dataset.defaultSortDirection || "asc");
    });
});

function compareCells(left, right) {
    const leftValue = sortValue(left);
    const rightValue = sortValue(right);
    if (typeof leftValue === "number" && typeof rightValue === "number") return leftValue - rightValue;
    return String(leftValue).localeCompare(String(rightValue), undefined, { numeric: true, sensitivity: "base" });
}

function sortValue(cell) {
    const value = cell?.dataset.sortValue ?? cell?.textContent.trim() ?? "";
    if (value === "") return "";
    const number = Number(value);
    return Number.isNaN(number) ? value : number;
}
