document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll("[data-sort-table]").forEach(makeSortable);
});

function makeSortable(table) {
    const headers = [...(table.tHead?.rows[0].cells ?? [])];
    const tbody = table.tBodies[0];
    if (!headers.length || !tbody) return;

    const sortRows = (column, direction) => {
        const rows = [...tbody.rows];
        rows.sort((left, right) => compareCells(left.cells[column], right.cells[column], direction));
        tbody.replaceChildren(...rows);
        headers.forEach((header, index) => header.classList.toggle("sorted-column", index === column));
        table.querySelectorAll("td.sorted-cell").forEach((cell) => cell.classList.remove("sorted-cell"));
        [...tbody.rows].forEach((row) => row.cells[column]?.classList.add("sorted-cell"));
        table.dataset.sortDirection = direction;
        table.dataset.sortColumn = column;
    };

    headers.forEach((header, column) => {
        header.addEventListener("click", (event) => {
            if (event.target.closest("button")) return;
            const sortedAscending = table.dataset.sortColumn === String(column) && table.dataset.sortDirection === "asc";
            sortRows(column, sortedAscending ? "desc" : "asc");
        });
    });

    const start = requestedSort(headers) ?? defaultSort(table, headers);
    if (start) sortRows(start.column, start.direction);
}

// A link may land on this page asking for one column, named so it survives the columns moving.
function requestedSort(headers) {
    const params = new URLSearchParams(window.location.search);
    const column = columnForKey(headers, params.get("sort"));
    if (column === null) return null;
    return { column, direction: params.get("dir") === "asc" ? "asc" : "desc" };
}

function defaultSort(table, headers) {
    const column = columnForKey(headers, table.dataset.defaultSortKey);
    if (column === null) return null;
    return { column, direction: table.dataset.defaultSortDirection || "asc" };
}

function columnForKey(headers, key) {
    if (!key) return null;
    const column = headers.findIndex((header) => header.dataset.sortKey === key);
    return column === -1 ? null : column;
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
