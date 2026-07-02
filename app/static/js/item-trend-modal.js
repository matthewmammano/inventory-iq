(function () {
    const modal = document.querySelector("#item-trend-modal");
    const chart = document.querySelector("#item-trend-chart");
    const title = document.querySelector("#item-trend-title");
    const summary = document.querySelector("#item-trend-summary");
    const scales = document.querySelector("#item-trend-scales");
    const close = document.querySelector("#item-trend-close");
    if (!modal || !chart || !title || !summary || !scales || !close) return;

    const DAY_MS = 86_400_000;
    const RANGE_OPTIONS = [
        { key: "all", label: "Full History", days: null },
        { key: "year", label: "Past Year", days: 365 },
        { key: "sixMonths", label: "Past 6 Months", days: 183 },
        { key: "month", label: "Past Month", days: 30 },
        { key: "week", label: "Past Week", days: 7 },
    ];
    let activeRangeKey = "all";
    let activePayload = null;

    const open = async (url) => {
        modal.classList.remove("hidden");
        chart.innerHTML = '<div class="item-trend-empty">Loading...</div>';
        scales.innerHTML = "";
        title.textContent = "Item Trend";
        summary.textContent = "";
        const response = await fetch(url, { headers: { Accept: "application/json" } });
        if (!response.ok) throw new Error("Trend fetch failed");
        activePayload = await response.json();
        activeRangeKey = "all";
        render(activePayload);
    };

    const render = (payload) => {
        title.textContent = `${payload.item_name} - ${payload.location_name}`;
        summary.textContent = payload.trend_per_day === null
            ? "No trained trend yet"
            : `${payload.trend_rate_display}, ${Math.round(payload.confidence_percent || 0)}% confidence`;
        const rangeOptions = availableRanges(payload);
        if (!rangeOptions.some((option) => option.key === activeRangeKey && !option.disabled)) {
            activeRangeKey = "all";
        }
        renderScaleButtons(rangeOptions);
        const filteredPayload = filterPayload(payload, activeRangeKey);
        const points = [...filteredPayload.count_points, ...filteredPayload.operation_points, ...filteredPayload.trendline_points];
        if (!points.length) {
            chart.innerHTML = '<div class="item-trend-empty">No history yet</div>';
            return;
        }
        chart.innerHTML = buildSvg(filteredPayload, scale(points));
    };

    const renderScaleButtons = (rangeOptions) => {
        scales.innerHTML = rangeOptions.map((option) => `
            <button
                class="item-trend-scale-button${option.key === activeRangeKey ? " is-active" : ""}"
                type="button"
                data-range-key="${option.key}"
                aria-pressed="${option.key === activeRangeKey}"
                ${option.disabled ? 'disabled title="Not enough history for this range"' : ""}>
                ${option.label}
            </button>
        `).join("");
    };

    const availableRanges = (payload) => {
        const historySpanMs = historySpan(payload);
        return RANGE_OPTIONS.map((option) => ({
            ...option,
            disabled: option.days !== null && historySpanMs < option.days * DAY_MS,
        }));
    };

    const historySpan = (payload) => {
        const historyPoints = [...payload.count_points, ...payload.operation_points];
        if (historyPoints.length < 2) return 0;
        const times = historyPoints.map((point) => new Date(point.at).getTime());
        return Math.max(...times) - Math.min(...times);
    };

    const filterPayload = (payload, rangeKey) => {
        const range = RANGE_OPTIONS.find((option) => option.key === rangeKey);
        if (!range || range.days === null) return payload;
        const cutoff = latestPointTime(payload) - range.days * DAY_MS;
        return {
            ...payload,
            count_points: payload.count_points.filter((point) => new Date(point.at).getTime() >= cutoff),
            operation_points: payload.operation_points.filter((point) => new Date(point.at).getTime() >= cutoff),
            trendline_points: visibleTrendlinePoints(payload.trendline_points, cutoff),
        };
    };

    const visibleTrendlinePoints = (trendlinePoints, cutoff) => {
        if (trendlinePoints.length < 2) return trendlinePoints.filter((point) => new Date(point.at).getTime() >= cutoff);
        const [startPoint, endPoint] = trendlinePoints;
        const startTime = new Date(startPoint.at).getTime();
        const endTime = new Date(endPoint.at).getTime();
        if (endTime <= cutoff) return [];
        if (startTime >= cutoff) return trendlinePoints;
        const ratio = (cutoff - startTime) / Math.max(endTime - startTime, 1);
        return [
            {
                ...startPoint,
                at: new Date(cutoff).toISOString(),
                quantity: roundQuantity(startPoint.quantity + ((endPoint.quantity - startPoint.quantity) * ratio)),
            },
            endPoint,
        ];
    };

    const latestPointTime = (payload) => Math.max(
        ...[...payload.count_points, ...payload.operation_points, ...payload.trendline_points]
            .map((point) => new Date(point.at).getTime()),
    );

    const scale = (points) => {
        const times = points.map((point) => new Date(point.at).getTime());
        const quantities = points.map((point) => point.quantity);
        const minTime = Math.min(...times);
        const maxTime = Math.max(...times);
        const timeSpan = Math.max(maxTime - minTime, 1);
        const maxQuantity = Math.max(...quantities, 1);
        return {
            maxQuantity,
            minDate: new Date(minTime),
            maxDate: new Date(maxTime),
            x: (at) => 68 + ((new Date(at).getTime() - minTime) / timeSpan) * 844,
            y: (quantity) => 306 - (quantity / maxQuantity) * 236,
        };
    };

    const buildSvg = (payload, s) => `
        <svg viewBox="0 0 980 360" role="img" aria-label="Item inventory trend">
            <text x="26" y="40" font-size="15" font-weight="800" fill="#20242a">Quantity (units)</text>
            <text x="68" y="342" font-size="14" font-weight="800" fill="#20242a">${dateLabel(s.minDate)}</text>
            <text x="912" y="342" text-anchor="end" font-size="14" font-weight="800" fill="#20242a">${dateLabel(s.maxDate)}</text>
            ${yAxisLabels(s).map((label) => `
                <text x="40" y="${label.y}" text-anchor="end" font-size="13" fill="#605f56">${label.value}</text>
            `).join("")}
            <line x1="68" y1="306" x2="912" y2="306" stroke="#81734c" stroke-width="2"/>
            <line x1="68" y1="70" x2="68" y2="306" stroke="#81734c" stroke-width="2"/>
            ${polyline(payload.count_points, s, "#1f4e79", 3)}
            ${payload.operation_points.map((p) => dot(p, s, 4, "#9b5b18")).join("")}
            ${payload.count_points.map((p) => dot(p, s, 8, "#1f4e79")).join("")}
            ${polyline(payload.trendline_points, s, "#9f3434", 5)}
            ${currentEstimateMarker(payload.trendline_points, s)}
        </svg>`;

    const polyline = (points, s, color, width) => points.length < 2 ? "" :
        `<polyline fill="none" stroke="${color}" stroke-width="${width}" points="${points.map((p) => `${s.x(p.at)},${s.y(p.quantity)}`).join(" ")}"/>`;

    const dot = (point, s, radius, color) =>
        `<circle cx="${s.x(point.at)}" cy="${s.y(point.quantity)}" r="${radius}" fill="${color}"><title>${point.operation}: ${point.quantity}</title></circle>`;

    const currentEstimateMarker = (trendlinePoints, s) => {
        if (!trendlinePoints.length) return "";
        const point = trendlinePoints[trendlinePoints.length - 1];
        const x = s.x(point.at);
        const y = s.y(point.quantity);
        return `
            <circle cx="${x}" cy="${y}" r="10" fill="#ffffff" stroke="#9f3434" stroke-width="3">
                <title>Current estimate: ${point.quantity}</title>
            </circle>
            <circle cx="${x}" cy="${y}" r="4" fill="#9f3434" aria-hidden="true"></circle>
        `;
    };

    const yAxisLabels = (s) => {
        const maxLabelValue = Math.ceil(s.maxQuantity);
        const labels = [
            { value: maxLabelValue, quantity: s.maxQuantity },
            { value: 0, quantity: 0 },
        ];
        if (s.maxQuantity > 6) {
            labels.splice(
                1,
                0,
                { value: Math.round(s.maxQuantity * 0.75), quantity: s.maxQuantity * 0.75 },
                { value: Math.round(s.maxQuantity * 0.5), quantity: s.maxQuantity * 0.5 },
                { value: Math.round(s.maxQuantity * 0.25), quantity: s.maxQuantity * 0.25 },
            );
        }
        return labels.map((label) => ({ ...label, y: s.y(label.quantity) + 4 }));
    };

    const dateLabel = (date) => date.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
    const roundQuantity = (value) => Math.round(value * 100) / 100;

    document.querySelectorAll("[data-trend-url]").forEach((button) => {
        button.addEventListener("click", () => open(button.dataset.trendUrl).catch(() => {
            activePayload = null;
            scales.innerHTML = "";
            chart.innerHTML = '<div class="item-trend-empty">Could not load trend</div>';
        }));
    });
    scales.addEventListener("click", (event) => {
        const button = event.target.closest("[data-range-key]");
        if (!button || button.disabled || !activePayload) return;
        activeRangeKey = button.dataset.rangeKey;
        render(activePayload);
    });
    close.addEventListener("click", () => modal.classList.add("hidden"));
    modal.addEventListener("click", (event) => {
        if (event.target === modal) modal.classList.add("hidden");
    });
})();
