document.addEventListener("DOMContentLoaded", () => {
    const ACTIVITY_EVENTS = ["pointerdown", "pointermove", "keydown", "wheel", "scroll", "touchstart", "touchmove"];
    const TICK_INTERVAL_MS = 250;
    const MS_PER_SECOND = 1000;

    const panel = document.querySelector("#idle-timeout");
    const countdown = panel?.querySelector("[data-idle-countdown]");
    if (!panel || !countdown) return;

    const { homeUrl, idleSeconds, warningSeconds } = panel.dataset;
    const warningStartsAt = (Number(idleSeconds) - Number(warningSeconds)) * MS_PER_SECOND;
    if (!homeUrl || !Number(idleSeconds) || !Number(warningSeconds)) return;

    let lastActivityAt = Date.now();
    let warningShown = false;

    function markActivity() {
        lastActivityAt = Date.now();
        if (warningShown) {
            warningShown = false;
            panel.classList.add("hidden");
        }
    }

    function tick() {
        const idleMs = Date.now() - lastActivityAt;
        if (idleMs < warningStartsAt) return;
        if (!warningShown) {
            warningShown = true;
            panel.classList.remove("hidden");
        }
        const secondsLeft = Math.ceil((Number(idleSeconds) * MS_PER_SECOND - idleMs) / MS_PER_SECOND);
        countdown.textContent = String(Math.max(secondsLeft, 0));
        if (secondsLeft <= 0) {
            window.InventoryLoadingOverlay?.show({ immediate: true });
            window.location.href = homeUrl;
        }
    }

    ACTIVITY_EVENTS.forEach((name) => document.addEventListener(name, markActivity, { capture: true, passive: true }));
    setInterval(tick, TICK_INTERVAL_MS);
});
