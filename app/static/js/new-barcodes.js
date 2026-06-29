document.addEventListener("DOMContentLoaded", () => {
    const form = document.querySelector(".upc-add-form");
    const input = form?.querySelector("input[name='upc']");
    const formValidation = window.InventoryFormValidation;
    if (!form || !input || !formValidation) return;

    const normalizedInput = () => input.value.trim();

    const submitIfValid = () => {
        input.value = normalizedInput();
        const message = input.value ? formValidation.upcError(input.value) : "Enter a UPC.";
        if (message) {
            input.value = "";
            window.InventoryFlash?.show("warning", message);
            return false;
        }
        return true;
    };

    const addUpc = (upc) => {
        input.value = upc;
        if (submitIfValid()) form.requestSubmit();
    };

    input.addEventListener("input", () => {
        input.value = input.value.replace(/\D/g, "").slice(0, 12);
    });
    form.addEventListener("submit", (event) => {
        if (!submitIfValid()) event.preventDefault();
    });
    document.querySelectorAll(".upc-review-link").forEach((linkForm) => {
        linkForm.addEventListener("submit", (event) => {
            const select = linkForm.querySelector("select[name='item_id']");
            if (select?.value) return;
            event.preventDefault();
            const upc = linkForm.closest("tr")?.querySelector("td")?.textContent?.trim() || "this UPC";
            window.InventoryFlash?.show("warning", `Select an item before linking UPC ${upc}.`);
        });
    });
    window.bindUpcScanner(addUpc);
});
