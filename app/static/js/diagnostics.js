(() => {
    "use strict";

    const REPORT_URL = "/api/debug/report";
    const SESSION_FLAG = "diagnosticsReported";
    let lastRequestId = null;

    function collectFields() {
        return {
            user_agent: navigator.userAgent,
            screen_px: `${screen.width}x${screen.height}`,
            viewport_px: `${window.innerWidth}x${window.innerHeight}`,
            pixel_ratio: window.devicePixelRatio || 1,
            color_depth: screen.colorDepth,
            touch: navigator.maxTouchPoints > 0,
            cpu_cores: navigator.hardwareConcurrency ?? null,
            memory_gb: navigator.deviceMemory ?? null,
            timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
            locale: navigator.language,
        };
    }

    function sendReport(correlatedRequestId) {
        const payload = collectFields();
        if (correlatedRequestId) {
            payload.correlated_request_id = correlatedRequestId;
        }
        fetch(REPORT_URL, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
            keepalive: true,
        }).catch(() => {});
    }

    const originalFetch = window.fetch.bind(window);
    window.fetch = (...args) =>
        originalFetch(...args)
            .then((response) => {
                const requestId = response.headers.get("X-Request-ID");
                if (requestId) {
                    lastRequestId = requestId;
                }
                return response;
            })
            .catch((error) => {
                sendReport(lastRequestId);
                throw error;
            });

    window.addEventListener("error", () => sendReport(lastRequestId));
    window.addEventListener("unhandledrejection", () => sendReport(lastRequestId));

    if (!sessionStorage.getItem(SESSION_FLAG)) {
        sessionStorage.setItem(SESSION_FLAG, "1");
        sendReport(null);
    }
})();
