document.addEventListener("DOMContentLoaded", () => {
    const tips = [...document.querySelectorAll(".info-tip")];
    if (!tips.length) return;

    function setOpen(tip, open) {
        tip.classList.toggle("is-open", open);
        tip.setAttribute("aria-expanded", String(open));
    }

    function closeAll() {
        tips.forEach((tip) => setOpen(tip, false));
    }

    tips.forEach((tip) => {
        setOpen(tip, false);
        tip.addEventListener("click", (event) => {
            // the header this sits in sorts the table on click
            event.stopPropagation();
            const open = !tip.classList.contains("is-open");
            closeAll();
            setOpen(tip, open);
        });
    });

    document.addEventListener("click", closeAll);
    document.addEventListener("keydown", (event) => {
        if (event.key !== "Escape") return;
        // blurring matters: :focus-visible would otherwise keep the bubble on screen
        if (document.activeElement?.classList.contains("info-tip")) document.activeElement.blur();
        closeAll();
    });
});
