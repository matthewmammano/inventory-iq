document.addEventListener("DOMContentLoaded", () => {
    const modal = document.querySelector("#history-print-modal");
    const openButtons = document.querySelectorAll("[data-history-modal-open]");
    const closeButtons = document.querySelectorAll("[data-history-modal-close]");
    const form = document.querySelector("[data-history-print-form]");
    const printArea = document.querySelector("#history-print-area");
    const printButton = document.querySelector("[data-history-print-submit]");
    const emailSection = document.querySelector("[data-history-email-section]");
    const emailEmpty = document.querySelector("[data-history-email-empty]");
    const emailSubmit = document.querySelector("[data-history-email-submit]");
    const dateInputs = [...document.querySelectorAll("[data-history-date]")];
    const formValidation = window.InventoryFormValidation;

    const cleanupPrintState = () => {
        document.body.classList.remove("printing-report");
        printArea?.replaceChildren();
    };

    const todayInTimezone = (timezone) => {
        const parts = new Intl.DateTimeFormat("en-US", {
            timeZone: timezone || undefined,
            year: "numeric",
            month: "2-digit",
            day: "2-digit",
        }).formatToParts(new Date());
        const value = (type) => parts.find((part) => part.type === type)?.value || "";
        return `${value("year")}-${value("month")}-${value("day")}`;
    };

    const refreshDateLimits = () => {
        const maxDate = todayInTimezone(modal?.dataset.userTimezone || "");
        dateInputs.forEach((input) => {
            input.max = maxDate;
            input.dataset.maxDate = maxDate;
        });
    };

    const resetModalValidationState = () => {
        dateInputs.forEach((input) => formValidation?.clearFieldState(input));
    };

    const setModalMode = (mode) => {
        const emailMode = mode === "email";
        emailSection?.classList.toggle("hidden", !emailMode);
        emailEmpty?.classList.toggle("hidden", !emailMode);
        emailSubmit?.classList.toggle("hidden", !emailMode);
        printButton?.classList.toggle("hidden", emailMode);
    };

    openButtons.forEach((button) =>
        button.addEventListener("click", () => {
            refreshDateLimits();
            resetModalValidationState();
            setModalMode(button.dataset.historyModalOpen || "print");
            modal?.classList.remove("hidden");
        }),
    );
    closeButtons.forEach((button) =>
        button.addEventListener("click", () => {
            resetModalValidationState();
            modal?.classList.add("hidden");
        }),
    );
    printButton?.addEventListener("click", async () => {
        if (!form || !formValidation || !printArea) return;
        if (!(await formValidation.validateForm(form))) return;
        const url = `${modal?.dataset.printAction}?${new URLSearchParams(new FormData(form))}`;
        window.InventoryLoadingOverlay?.show({ immediate: true });
        try {
            const response = await fetch(url, { headers: { "X-Requested-With": "fetch" } });
            if (!response.ok) throw new Error(await response.text());
            printArea.innerHTML = await response.text();
            modal?.classList.add("hidden");
            window.InventoryLoadingOverlay?.hide();
            document.body.classList.add("printing-report");
            window.print();
            window.setTimeout(cleanupPrintState, 250);
        } catch (error) {
            window.InventoryLoadingOverlay?.hide();
            cleanupPrintState();
            const message = error.message || "Could not load print history.";
            const target = form.querySelector(message.startsWith("Start date") ? "[name='start_date']" : "[name='end_date']");
            if (!target) return;
            formValidation.setExternalError(target, message);
            await formValidation.validateField(target);
        }
    });

    window.addEventListener("afterprint", cleanupPrintState);
    document.addEventListener("visibilitychange", () => {
        if (!document.hidden) window.setTimeout(cleanupPrintState, 250);
    });
});
