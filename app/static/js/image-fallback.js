document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll("img[data-fallback-src]").forEach((image) => {
        image.addEventListener("error", () => {
            image.src = image.dataset.fallbackSrc;
        }, { once: true });
    });
});
