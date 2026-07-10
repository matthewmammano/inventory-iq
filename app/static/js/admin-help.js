document.addEventListener("DOMContentLoaded", () => {
    const root = document.querySelector("[data-admin-help]");
    if (!root) return;

    const search = root.querySelector("#admin-help-search");
    const tagButtons = [...root.querySelectorAll("[data-help-tag]")];
    const grid = document.querySelector(".help-card-grid");
    const articles = [...document.querySelectorAll("[data-help-article]")].map((element, index) => ({
        element,
        index,
        tags: (element.dataset.helpTags || "").split("|"),
        title: element.dataset.helpTitle || "",
        summary: element.dataset.helpSummary || "",
        search: element.dataset.helpSearch || "",
    }));
    const empty = document.querySelector("[data-help-empty]");
    const fuse = buildSearch(articles);
    let selectedTag = "";

    function matchesSelectedTag(article) {
        return !selectedTag || article.tags.includes(selectedTag);
    }

    function updateTagButtons() {
        tagButtons.forEach((button) => {
            const selected = button.dataset.helpTag === selectedTag;
            button.classList.toggle("is-selected", selected);
            button.setAttribute("aria-pressed", selected ? "true" : "false");
        });
    }

    function updateResults() {
        const query = search.value.trim();
        const matches = query ? fuse.search(query) : null;
        const scoreByIndex = new Map(matches ? matches.map((result) => [result.item.index, result.score ?? 0]) : []);

        const ordered = query
            ? [...articles].sort((first, second) => {
                  const firstMatched = scoreByIndex.has(first.index);
                  const secondMatched = scoreByIndex.has(second.index);
                  if (firstMatched !== secondMatched) return firstMatched ? -1 : 1;
                  if (firstMatched && secondMatched) return scoreByIndex.get(first.index) - scoreByIndex.get(second.index);
                  return first.index - second.index;
              })
            : articles;

        let visibleCount = 0;
        ordered.forEach((article) => {
            const visible = matchesSelectedTag(article) && (!query || scoreByIndex.has(article.index));
            article.element.hidden = !visible;
            visibleCount += Number(visible);
            grid.appendChild(article.element);
        });
        empty.classList.toggle("hidden", visibleCount !== 0);
        updateTagButtons();
    }

    tagButtons.forEach((button) => {
        button.addEventListener("click", () => {
            selectedTag = selectedTag === button.dataset.helpTag ? "" : button.dataset.helpTag;
            updateResults();
        });
    });
    search.addEventListener("input", updateResults);
    updateResults();
});

function buildSearch(articles) {
    if (typeof Fuse !== "undefined") {
        return new Fuse(articles, {
            keys: [
                { name: "title", weight: 0.5 },
                { name: "tags", weight: 0.25 },
                { name: "summary", weight: 0.15 },
                { name: "search", weight: 0.1 },
            ],
            threshold: 0.35,
            ignoreLocation: true,
            includeScore: true,
        });
    }
    return {
        search: (query) => {
            const normalized = query.toLowerCase();
            return articles
                .filter((article) => `${article.title} ${article.summary} ${article.tags.join(" ")} ${article.search}`.toLowerCase().includes(normalized))
                .map((item) => ({ item, score: 0 }));
        },
    };
}
