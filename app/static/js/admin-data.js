document.addEventListener("DOMContentLoaded", () => {
    const formValidation = window.InventoryFormValidation;
    const section = document.querySelector("#notifications[data-existing-emails]");
    if (!formValidation || !section) return;

    const existingEmails = JSON.parse(section.dataset.existingEmails);
    const duplicateMessage = "A notification recipient already exists for this email.";

    section.querySelectorAll('input[name="email"]').forEach((field) => {
        const checkDuplicate = () => {
            const isDuplicate = field.value !== field.defaultValue && existingEmails.includes(field.value);
            formValidation.setExternalError(field, isDuplicate ? duplicateMessage : "");
            formValidation.validateField(field);
        };
        field.addEventListener("input", checkDuplicate);
        field.addEventListener("blur", checkDuplicate);
    });
});
