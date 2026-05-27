document.addEventListener("DOMContentLoaded", () => {
    const search = document.querySelector("#search");
    const list = document.querySelector("#results");
    if (!search || !list) return;

    const items = JSON.parse(list.dataset.items || "[]");
    const squad = list.dataset.squad;
    const isAdmin = list.dataset.admin === "true";
    const fuse = buildSearch(items);

    function itemUrl(itemId) {
        const base = `/inventory/${encodeURIComponent(squad)}`;
        return isAdmin ? `${base}/admin-panel/scan?item_id=${itemId}` : `${base}/scan?item_id=${itemId}`;
    }

    function upcUrl(upc) {
        const base = `/inventory/${encodeURIComponent(squad)}`;
        return isAdmin ? `${base}/admin-panel/scan?upc=${upc}` : `${base}/scan?upc=${upc}`;
    }

    function showResults(query) {
        const results = query.trim() ? fuse.search(query) : items.map((item) => ({ item, score: 0 }));
        results.sort((a, b) =>
            a.score !== b.score
                ? a.score - b.score
                : new Date(b.item.last_accessed || 0) - new Date(a.item.last_accessed || 0)
        );
        list.innerHTML = "";
        results.slice(0, 5).forEach(({ item }) => list.appendChild(resultRow(item, itemUrl)));
    }

    search.focus();
    search.addEventListener("input", (event) => {
        const value = event.target.value.trim();
        if (/^\d{12}$/.test(value)) {
            window.location.href = upcUrl(value);
            return;
        }
        showResults(value);
    });
    showResults("");
    bindUpcScanner(upcUrl);
});

function buildSearch(items) {
    if (typeof Fuse !== "undefined") {
        return new Fuse(items, { keys: ["name", "upc", "tags"], threshold: 0.9, includeScore: true });
    }
    return {
        search: (query) => items
            .filter((item) => searchableText(item).includes(query.toLowerCase()))
            .map((item) => ({ item, score: 0 })),
    };
}

function searchableText(item) {
    return `${item.name} ${item.upc} ${item.tags.join(" ")}`.toLowerCase();
}

function resultRow(item, itemUrl) {
    const row = document.createElement("li");
    const tags = item.tag_data.map((tag) =>
        `<span class="tag" style="background-color: ${tag.color}; color: ${tag.text_color}; border-color: ${tag.text_color};">${tag.name}</span>`
    ).join("");
    row.innerHTML = `<div class="result-title"><strong>${item.name}</strong><div class="tags">${tags}</div></div>`;
    row.addEventListener("click", () => { window.location.href = itemUrl(item.id); });
    return row;
}

function bindUpcScanner(upcUrl) {
    let buffer = "";
    let timeout;
    const redirect = (upc) => { window.location.href = upcUrl(upc); };

    document.addEventListener("paste", (event) => {
        const text = event.clipboardData?.getData("text")?.trim();
        if (/^\d{12}$/.test(text)) redirect(text);
    });

    document.addEventListener("keydown", (event) => {
        clearTimeout(timeout);
        if (event.key === "Enter" && buffer.length === 12) {
            event.preventDefault();
            redirect(buffer);
            buffer = "";
            return;
        }
        if (/^\d$/.test(event.key)) {
            buffer = (buffer + event.key).slice(-12);
            timeout = setTimeout(() => {
                if (buffer.length === 12) redirect(buffer);
                buffer = "";
            }, 100);
            return;
        }
        if (event.key !== "Enter") buffer = "";
    });
}
