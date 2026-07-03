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
        title: normalize(element.dataset.helpTitle),
        summary: normalize(element.dataset.helpSummary),
        search: normalize(element.dataset.helpSearch),
    }));
    const empty = document.querySelector("[data-help-empty]");
    let selectedTag = "";

    function normalize(value) {
        return (value || "").toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
    }

    function queryTerms() {
        return normalize(search.value).split(" ").filter(Boolean);
    }

    function updateTagButtons() {
        tagButtons.forEach((button) => {
            const selected = button.dataset.helpTag === selectedTag;
            button.classList.toggle("is-selected", selected);
            button.setAttribute("aria-pressed", selected ? "true" : "false");
        });
    }

    function termScore(article, term) {
        if (article.title.split(" ").some((word) => word.startsWith(term))) return 90;
        if (article.title.includes(term)) return 70;
        if (article.tags.some((tag) => tag.includes(term))) return 55;
        if (article.summary.includes(term)) return 35;
        return article.search.includes(term) ? 10 : 0;
    }

    function matchesSelectedTag(article) {
        return !selectedTag || article.tags.includes(selectedTag);
    }

    function searchScore(article, terms) {
        if (terms.length === 0) return 0;

        let score = 0;
        for (const term of terms) {
            const scoreForTerm = termScore(article, term);
            if (scoreForTerm === 0) return -1;
            score += scoreForTerm;
        }
        return score;
    }

    function updateResults() {
        const terms = queryTerms();
        const filteredArticles = articles.map((article) => ({
            ...article,
            visible: matchesSelectedTag(article),
            score: searchScore(article, terms),
        })).map((article) => ({
            ...article,
            visible: article.visible && article.score >= 0,
        }));
        const orderedArticles = terms.length
            ? [...filteredArticles].sort((first, second) => second.score - first.score || first.index - second.index)
            : filteredArticles;

        let visibleCount = 0;
        orderedArticles.forEach((article) => {
            article.element.hidden = !article.visible;
            visibleCount += Number(article.visible);
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
