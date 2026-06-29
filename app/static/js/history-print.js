document.addEventListener("DOMContentLoaded", () => {
    const modal = document.querySelector("#history-print-modal");
    const openButton = document.querySelector("#open-history-print");
    const closeButton = document.querySelector("#close-history-print");
    const form = document.querySelector("[data-history-print-form]");
    const printArea = document.querySelector("#history-print-area");
    const dateInputs = [...document.querySelectorAll("#history-print-start, #history-print-end")];
    const formValidation = window.InventoryFormValidation;

    openButton?.addEventListener("click", () => modal?.classList.remove("hidden"));
    closeButton?.addEventListener("click", () => modal?.classList.add("hidden"));
    dateInputs.forEach((input) => {
        input.addEventListener("input", () => {
            input.value = input.value.replace(/^(\d{4})\d+(-.*)?$/, "$1$2");
        });
    });
    form?.addEventListener("submit", async (event) => {
        event.preventDefault();
        if (!form || !formValidation || !printArea) return;
        if (!(await formValidation.validateForm(form))) return;
        const url = `${form.action}?${new URLSearchParams(new FormData(form))}`;
        window.InventoryLoadingOverlay?.show({ immediate: true });
        try {
            const response = await fetch(url, { headers: { "X-Requested-With": "fetch" } });
            if (!response.ok) throw new Error(await response.text());
            printArea.innerHTML = await response.text();
            modal?.classList.add("hidden");
            window.InventoryLoadingOverlay?.hide();
            document.body.classList.add("printing-history");
            window.print();
        } catch (error) {
            window.InventoryLoadingOverlay?.hide();
            const message = error.message || "Could not load print history.";
            const target = form.querySelector(message.startsWith("Start date") ? "[name='start_date']" : "[name='end_date']");
            if (!target) return;
            formValidation.setExternalError(target, message);
            await formValidation.validateField(target);
        }
    });

    window.addEventListener("afterprint", () => {
        document.body.classList.remove("printing-history");
        if (printArea) printArea.replaceChildren();
    });
});
