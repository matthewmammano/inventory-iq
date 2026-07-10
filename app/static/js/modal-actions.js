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
        trigger.addEventListener("click", () => {
            confirmPanel?.classList.remove("hidden");
            trigger.classList.add("hidden");
        });
        confirmPanel?.querySelector("[data-delete-cancel]")?.addEventListener("click", () => {
            confirmPanel.classList.add("hidden");
            trigger.classList.remove("hidden");
        });
    });
});
