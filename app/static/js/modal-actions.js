document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll("[data-modal-open]").forEach((button) => {
        const modal = document.getElementById(button.dataset.modalOpen);
        button.addEventListener("click", () => {
            modal?.classList.remove("hidden");
            modal?.querySelectorAll("[data-countdown-seconds]").forEach(holdUntilCountdownEnds);
        });
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

// A destructive confirm stays unclickable until its countdown ends, so nobody taps through it by reflex.
function holdUntilCountdownEnds(control) {
    const label = (control.dataset.countdownLabel ??= control.textContent.trim());
    let remaining = Number(control.dataset.countdownSeconds);

    control.classList.add("counting-down");
    control.setAttribute("tabindex", "-1");
    control.textContent = `${label} (${remaining})`;

    const tick = setInterval(() => {
        remaining -= 1;
        control.textContent = remaining > 0 ? `${label} (${remaining})` : label;
        if (remaining > 0) return;
        clearInterval(tick);
        control.classList.remove("counting-down");
        control.removeAttribute("tabindex");
    }, 1000);
}
