document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll("[data-email-modal]").forEach((modal) => {
        const closeButtons = modal.querySelectorAll("[data-email-modal-close]");
        const submitButton = modal.querySelector("[data-email-submit]");
        const selectAll = modal.querySelector("[data-email-select-all]");
        const options = [...modal.querySelectorAll("[data-email-recipient-option]")];
        const syncState = () => {
            if (submitButton) submitButton.disabled = options.length > 0 && !options.some((option) => option.checked);
            if (selectAll) selectAll.checked = options.length > 0 && options.every((option) => option.checked);
        };

        document.querySelectorAll(`[data-email-modal-open="${modal.id}"]`).forEach((button) => {
            button.addEventListener("click", () => modal.classList.remove("hidden"));
        });
        closeButtons.forEach((button) => button.addEventListener("click", () => modal.classList.add("hidden")));
        selectAll?.addEventListener("change", () => {
            options.forEach((option) => {
                option.checked = selectAll.checked;
            });
            syncState();
        });
        options.forEach((option) => option.addEventListener("change", syncState));
        syncState();
    });
});
