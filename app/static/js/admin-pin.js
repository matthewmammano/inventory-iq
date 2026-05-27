document.addEventListener("DOMContentLoaded", () => {
    const form = document.querySelector(".login-panel");
    const pinInput = document.querySelector("#pin-value");
    const pinDisplay = document.querySelector("#pin-display");
    if (!form || !pinInput || !pinDisplay) return;

    function renderPin() {
        pinDisplay.textContent = ("*".repeat(pinInput.value.length) + "----").slice(0, 4);
    }

    function addDigit(digit) {
        pinInput.value = (pinInput.value + digit).slice(0, 4);
        renderPin();
    }

    document.querySelectorAll("[data-digit]").forEach((button) => {
        button.addEventListener("click", () => addDigit(button.dataset.digit));
    });
    document.querySelector(".clear").addEventListener("click", () => {
        pinInput.value = "";
        renderPin();
    });
    document.addEventListener("keydown", (event) => {
        if (/^\d$/.test(event.key)) {
            event.preventDefault();
            addDigit(event.key);
            return;
        }
        if (event.key === "Backspace") {
            event.preventDefault();
            pinInput.value = pinInput.value.slice(0, -1);
            renderPin();
            return;
        }
        if (event.key === "Enter") {
            event.preventDefault();
            form.requestSubmit();
        }
    });
});
