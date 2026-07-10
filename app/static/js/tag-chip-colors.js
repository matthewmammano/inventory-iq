document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll(".tag[data-tag-bg]").forEach((chip) => {
        chip.style.backgroundColor = chip.dataset.tagBg;
        chip.style.color = chip.dataset.tagFg;
        chip.style.borderColor = chip.dataset.tagFg;
    });
});
