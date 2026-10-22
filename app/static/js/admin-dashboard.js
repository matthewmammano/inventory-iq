document.addEventListener("DOMContentLoaded", () => {
    const track = document.querySelector("[data-attention-track]");
    if (!track) return;
    const arrows = [...document.querySelectorAll("[data-attention-scroll]")];

    const syncArrows = () => {
        const furthest = track.scrollWidth - track.clientWidth - 1;
        arrows.forEach((arrow) => {
            const forward = Number(arrow.dataset.attentionScroll) > 0;
            arrow.disabled = forward ? track.scrollLeft >= furthest : track.scrollLeft <= 0;
        });
    };

    arrows.forEach((arrow) => {
        arrow.addEventListener("click", () => {
            track.scrollBy({ left: Number(arrow.dataset.attentionScroll) * track.clientWidth * 0.8, behavior: "smooth" });
        });
    });

    track.addEventListener("scroll", syncArrows, { passive: true });
    window.addEventListener("resize", syncArrows);
    syncArrows();
});
