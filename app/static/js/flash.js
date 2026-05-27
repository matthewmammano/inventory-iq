document.addEventListener("DOMContentLoaded", () => {
    const container = document.querySelector("#flash-container");
    if (!container || !container.dataset.message) return;

    const category = container.dataset.category || "info";
    const iconMap = { success: "OK", warning: "!", error: "X", info: "i" };
    document.querySelector("#flash-message").textContent = container.dataset.message;
    document.querySelector("#flash-icon").textContent = iconMap[category] || "i";
    container.classList.add("show", `flash-${category}`);

    const timer = document.querySelector("#timer");
    const startedAt = Date.now();
    const duration = 7000;
    function updateTimer() {
        const progress = Math.min((Date.now() - startedAt) / duration, 1) * 100;
        timer.style.background =
            `conic-gradient(var(--flash-light) ${progress}%, var(--flash-color) ${progress}%)`;
        if (progress < 100) requestAnimationFrame(updateTimer);
        else container.classList.remove("show");
    }
    requestAnimationFrame(updateTimer);
});
