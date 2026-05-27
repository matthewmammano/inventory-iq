document.addEventListener("DOMContentLoaded", () => {
    const modal = document.querySelector("#report-email-modal");
    const openButton = document.querySelector("#open-report-email");
    const closeButton = document.querySelector("#close-report-email");
    const sendButton = document.querySelector("#send-report-email");
    const selectAll = document.querySelector("#select-all-report-emails");
    const options = [...document.querySelectorAll(".report-email-option")];
    if (!modal || !openButton || !closeButton) return;

    const syncState = () => {
        if (sendButton) sendButton.disabled = !options.some((option) => option.checked);
        if (selectAll) selectAll.checked = options.length > 0 && options.every((option) => option.checked);
    };

    openButton.addEventListener("click", () => modal.classList.remove("hidden"));
    closeButton.addEventListener("click", () => modal.classList.add("hidden"));
    selectAll?.addEventListener("change", () => {
        options.forEach((option) => {
            option.checked = selectAll.checked;
        });
        syncState();
    });
    options.forEach((option) => option.addEventListener("change", syncState));
    syncState();
});
