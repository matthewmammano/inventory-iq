document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll("[data-modal-open]").forEach((button) => {
        const modal = document.getElementById(button.dataset.modalOpen);
        button.addEventListener("click", () => modal?.classList.remove("hidden"));
    });

    document.querySelectorAll(".modal-backdrop").forEach((modal) => {
        modal.querySelectorAll("[data-modal-close]").forEach((button) => {
            button.addEventListener("click", () => modal.classList.add("hidden"));
        });
        modal.addEventListener("click", (event) => {
            if (event.target === modal) modal.classList.add("hidden");
        });
    });

    document.querySelectorAll("[data-delete-trigger]").forEach((trigger) => {
        const confirmPanel = document.getElementById(trigger.dataset.deleteConfirmTarget);
        const editView = trigger.closest("[data-modal-view='edit']");
        trigger.addEventListener("click", () => {
            editView?.classList.add("hidden");
            confirmPanel?.classList.remove("hidden");
        });
        confirmPanel?.querySelector("[data-delete-cancel]")?.addEventListener("click", () => {
            confirmPanel.classList.add("hidden");
            editView?.classList.remove("hidden");
        });
    });
});
