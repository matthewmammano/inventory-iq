document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll("[data-print-trigger]").forEach((button) => {
        button.addEventListener("click", () => window.print());
    });
});
