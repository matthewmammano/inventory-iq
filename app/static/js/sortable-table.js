document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll("[data-sort-table]").forEach((table) => {
        const headers = [...table.querySelectorAll("th[data-sort-column]")];
        const tbody = table.tBodies[0];
        if (!tbody) return;

        const sortRows = (column, direction) => {
            const rows = [...tbody.rows];
            rows.sort((left, right) => compareCells(left.cells[column], right.cells[column], direction));
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

        const requested = requestedSort(table);
        const startColumn = requested?.column ?? Number(table.dataset.defaultSortColumn);
        if (Number.isInteger(startColumn)) sortRows(startColumn, requested?.direction || table.dataset.defaultSortDirection || "asc");
    });
});

// A link may land on this page asking for one column, named so the index can shift with the data.
function requestedSort(table) {
    const params = new URLSearchParams(window.location.search);
    const key = params.get("sort");
    if (!key) return null;
    const header = table.querySelector(`th[data-sort-key="${CSS.escape(key)}"]`);
    if (!header) return null;
    return { column: Number(header.dataset.sortColumn), direction: params.get("dir") === "asc" ? "asc" : "desc" };
}

function compareCells(left, right, direction) {
    const leftValue = sortValue(left);
    const rightValue = sortValue(right);
    const leftMissing = isMissingSortValue(leftValue);
    const rightMissing = isMissingSortValue(rightValue);
    if (leftMissing && rightMissing) return 0;
    if (leftMissing) return 1;
    if (rightMissing) return -1;

    const multiplier = direction === "asc" ? 1 : -1;
    if (typeof leftValue === "number" && typeof rightValue === "number") return multiplier * (leftValue - rightValue);
    return multiplier * String(leftValue).localeCompare(String(rightValue), undefined, { numeric: true, sensitivity: "base" });
}

function sortValue(cell) {
    const displayValue = cell?.textContent.trim() ?? "";
    if (isMissingDisplayValue(displayValue)) return "";
    const value = cell?.dataset.sortValue ?? displayValue;
    const number = Number(value);
    return Number.isNaN(number) ? value : number;
}

function isMissingSortValue(value) {
    return value === "" || isMissingDisplayValue(String(value));
}

function isMissingDisplayValue(value) {
    return ["", "-", "NA", "N/A"].includes(value.trim().toUpperCase());
}
