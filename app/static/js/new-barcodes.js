document.addEventListener("DOMContentLoaded", () => {
    const form = document.querySelector(".upc-add-form");
    const input = form?.querySelector("input[name='upc']");
    if (!form || !input) return;

    const addUpc = (upc) => {
        input.value = upc;
        form.requestSubmit();
    };

    input.addEventListener("input", () => {
        if (/^\d{12}$/.test(input.value.trim())) form.requestSubmit();
    });
    window.bindUpcScanner(addUpc);
});
