const MAX_VISIBLE_RESULTS = 7;
const SEARCH_THRESHOLD = 0.4;
const LOAD_FAILED_NOTE = "Could not load the item list. Close this page and open it again.";
const NO_ITEMS_NOTE = "No items here yet.";
const noMatchNote = (query) => `Nothing matches "${query}". Check the spelling or scan the barcode.`;

document.addEventListener("DOMContentLoaded", () => {
    const search = document.querySelector("#search");
    const list = document.querySelector("#results");
    if (!search || !list) return;

    const items = parseItems(list.dataset.items);
    if (!items) {
        list.replaceChildren(noteRow(LOAD_FAILED_NOTE, "search-note--error"));
        search.disabled = true;
        return;
    }

    const agencyId = list.dataset.agencyId;
    const isAdmin = list.dataset.admin === "true";
    const scanItemBase = list.dataset.scanItemBase;
    const scanErrorUrl = list.dataset.scanErrorUrl;
    const fromStorageId = list.dataset.fromStorageId;
    const toStorageId = list.dataset.toStorageId;
    const fuse = window.buildFuzzySearch(items, { keys: ["name", "upcs", "tags"], threshold: SEARCH_THRESHOLD });

    function itemUrl(itemId) {
        if (scanItemBase && fromStorageId && toStorageId) {
            const params = new URLSearchParams({
                item_id: String(itemId),
                from_storage_id: fromStorageId,
                to_storage_id: toStorageId,
            });
            return `${scanItemBase}?${params.toString()}`;
        }
        const base = `/inventory/${encodeURIComponent(agencyId)}`;
        return isAdmin ? `${base}/admin-panel/scan?item_id=${itemId}` : `${base}/scan?item_id=${itemId}`;
    }

    const scanUpc = (upc) => {
        const item = items.find((candidate) => (candidate.upcs || []).includes(upc));
        if (item) {
            navigateTo(itemUrl(item.id));
            return;
        }
        const errorUrl = new URL(scanErrorUrl || `${window.location.pathname}?scan_error=not_found`, window.location.origin);
        errorUrl.searchParams.set("unknown_upc", upc);
        navigateTo(errorUrl.toString());
    };

    function showResults(query) {
        const results = query.trim() ? fuse.search(query) : items.map((item) => ({ item, score: 0 }));
        results.sort((a, b) =>
            a.score !== b.score
                ? a.score - b.score
                : new Date(b.item.last_accessed || 0) - new Date(a.item.last_accessed || 0)
        );
        list.replaceChildren();
        if (!results.length) {
            list.appendChild(noteRow(query.trim() ? noMatchNote(query.trim()) : NO_ITEMS_NOTE));
            return;
        }
        results.slice(0, MAX_VISIBLE_RESULTS).forEach(({ item }) => list.appendChild(resultRow(item, itemUrl)));
    }

    if (!window.matchMedia("(pointer: coarse)").matches) search.focus();
    search.addEventListener("input", (event) => {
        const value = event.target.value.trim();
        if (/^\d{12}$/.test(value)) {
            scanUpc(value);
            return;
        }
        showResults(value);
    });
    showResults("");
    window.bindUpcScanner(scanUpc);
});

function parseItems(raw) {
    try {
        return JSON.parse(raw || "[]");
    } catch {
        return null;
    }
}

function navigateTo(url) {
    window.InventoryLoadingOverlay?.show({ immediate: true });
    window.location.href = url;
}

function noteRow(text, variant) {
    const row = document.createElement("li");
    row.className = variant ? `search-note ${variant}` : "search-note";
    row.textContent = text;
    return row;
}

function resultRow(item, itemUrl) {
    const row = document.createElement("li");
    const title = document.createElement("div");
    title.className = "result-title";

    const name = document.createElement("strong");
    name.textContent = item.name;
    title.appendChild(name);

    const tags = document.createElement("div");
    tags.className = "tags";
    item.tag_data.forEach((tag) => tags.appendChild(tagBadge(tag)));
    title.appendChild(tags);

    row.appendChild(title);
    row.addEventListener("click", () => {
        navigateTo(itemUrl(item.id));
    });
    return row;
}

function tagBadge(tag) {
    const badge = document.createElement("span");
    badge.className = "tag";
    badge.textContent = tag.name;
    badge.style.backgroundColor = tag.color;
    badge.style.color = tag.text_color;
    badge.style.borderColor = tag.text_color;
    return badge;
}
