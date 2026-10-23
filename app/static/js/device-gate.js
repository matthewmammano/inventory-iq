const COOKIE_AGE_SECONDS = 60 * 60 * 24;
const KEYBOARD_COOKIE = "inventory_iq_keyboard";
const SMALL_SCREEN_COOKIE = "inventory_iq_small_screen_ok";
const RESIZE_SETTLE_MS = 200;

document.addEventListener("DOMContentLoaded", () => {
    const gate = document.querySelector("[data-device-gate]");
    if (!gate) return;

    gate.querySelector("[data-gate-keyboard-confirm]")?.addEventListener("click", () => grant(gate, KEYBOARD_COOKIE));
    gate.querySelector("[data-gate-continue]")?.addEventListener("click", () => grant(gate, SMALL_SCREEN_COOKIE));

    let settle;
    window.addEventListener("resize", () => {
        clearTimeout(settle);
        settle = setTimeout(() => applyGate(gate), RESIZE_SETTLE_MS);
    });

    applyGate(gate);
});

function applyGate(gate) {
    const blocker = reasonToBlock(gate);
    gate.classList.toggle("hidden", !blocker);
    document.body.classList.toggle("device-gate-open", Boolean(blocker));
    gate.querySelectorAll("[data-gate-reason]").forEach((panel) => panel.classList.toggle("hidden", panel.dataset.gateReason !== blocker));
}

function reasonToBlock(gate) {
    const minimumWidth = Number(gate.dataset.gateMinWidth);
    if (Number.isInteger(minimumWidth) && window.innerWidth < minimumWidth && !hasCookie(SMALL_SCREEN_COOKIE)) return "size";
    if (gate.dataset.gateKeyboard && !hasCookie(KEYBOARD_COOKIE)) return "keyboard";
    return null;
}

function grant(gate, name) {
    document.cookie = `${name}=1; max-age=${COOKIE_AGE_SECONDS}; path=/; samesite=lax`;
    applyGate(gate);
}

function hasCookie(name) {
    return document.cookie.split("; ").some((entry) => entry.startsWith(`${name}=`));
}
