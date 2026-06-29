document.addEventListener("DOMContentLoaded", () => {
    const container = document.querySelector("#flash-container");
    if (!container) return;

    const iconMap = { success: "OK", warning: "!", error: "X", info: "i" };
    let timerRun = 0;

    function show(category = "info", text = "", html = false) {
        if (!text) return;
        const message = document.querySelector("#flash-message");
        if (html) message.innerHTML = text;
        else message.textContent = text;
        document.querySelector("#flash-icon").textContent = iconMap[category] || "i";
        container.className = `flash-container show flash-${category}`;
        runTimer();
    }

    function runTimer() {
        timerRun += 1;
        const currentRun = timerRun;
        const timer = document.querySelector("#timer");
        const startedAt = Date.now();
        const duration = 7000;
        function updateTimer() {
            if (currentRun !== timerRun) return;
            const progress = Math.min((Date.now() - startedAt) / duration, 1) * 100;
            timer.style.background =
                `conic-gradient(var(--flash-light) ${progress}%, var(--flash-color) ${progress}%)`;
            if (progress < 100) requestAnimationFrame(updateTimer);
            else container.classList.remove("show");
        }
        requestAnimationFrame(updateTimer);
    }

    window.InventoryFlash = { show };
    show(container.dataset.category || "info", container.dataset.message, container.dataset.html === "1");
});
