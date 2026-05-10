document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll("[data-original-value]").forEach((input) => {
        const setDirtyState = () => {
            input.classList.toggle("is-dirty", input.value !== input.dataset.originalValue);
        };

        input.addEventListener("input", setDirtyState);
        setDirtyState();
    });
});
