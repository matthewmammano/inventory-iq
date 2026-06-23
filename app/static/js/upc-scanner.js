window.bindUpcScanner = (scanUpc) => {
    let buffer = "";
    let timeout;

    document.addEventListener("paste", (event) => {
        const text = event.clipboardData?.getData("text")?.trim();
        if (/^\d{12}$/.test(text)) scanUpc(text);
    });

    document.addEventListener("keydown", (event) => {
        if (event.target?.matches?.("input, select, textarea")) return;
        clearTimeout(timeout);
        if (event.key === "Enter" && buffer.length === 12) {
            event.preventDefault();
            scanUpc(buffer);
            buffer = "";
            return;
        }
        if (/^\d$/.test(event.key)) {
            buffer = (buffer + event.key).slice(-12);
            timeout = setTimeout(() => {
                if (buffer.length === 12) scanUpc(buffer);
                buffer = "";
            }, 100);
            return;
        }
        if (event.key !== "Enter") buffer = "";
    });
};
