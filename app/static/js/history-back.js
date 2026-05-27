document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll("[data-history-back]").forEach((link) => {
        link.addEventListener("click", (event) => {
            event.preventDefault();
            if (history.length > 1) history.back();
            else window.location.href = link.href;
        });
    });
});
