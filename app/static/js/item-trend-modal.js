(function () {
    const modal = document.querySelector("#item-trend-modal");
    const chart = document.querySelector("#item-trend-chart");
    const title = document.querySelector("#item-trend-title");
    const summary = document.querySelector("#item-trend-summary");
    const close = document.querySelector("#item-trend-close");
    if (!modal || !chart || !title || !summary || !close) return;

    const open = async (url) => {
        modal.classList.remove("hidden");
        chart.innerHTML = '<div class="item-trend-empty">Loading...</div>';
        const response = await fetch(url, { headers: { Accept: "application/json" } });
        if (!response.ok) throw new Error("Trend fetch failed");
        render(await response.json());
    };

    const render = (payload) => {
        title.textContent = `${payload.item_name} - ${payload.location_name}`;
        summary.textContent = payload.trend_per_day === null
            ? "No trained trend yet"
            : `${formatTrendRate(payload.trend_per_day)}, ${Math.round(payload.confidence_percent || 0)}% confidence`;
        const points = [...payload.count_points, ...payload.operation_points, ...payload.trendline_points];
        if (!points.length) {
            chart.innerHTML = '<div class="item-trend-empty">No history yet</div>';
            return;
        }
        chart.innerHTML = buildSvg(payload, scale(points));
    };

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
            <text x="490" y="342" text-anchor="middle" font-size="14" font-weight="800" fill="#20242a">Date</text>
            <text x="26" y="74" font-size="13" fill="#605f56">${Math.ceil(s.maxQuantity)}</text>
            <text x="40" y="310" font-size="13" fill="#605f56">0</text>
            <line x1="68" y1="306" x2="912" y2="306" stroke="#81734c" stroke-width="2"/>
            <line x1="68" y1="70" x2="68" y2="306" stroke="#81734c" stroke-width="2"/>
            ${polyline(payload.count_points, s, "#1f4e79", 3)}
            ${payload.operation_points.map((p) => dot(p, s, 4, "#9b5b18")).join("")}
            ${payload.count_points.map((p) => dot(p, s, 8, "#1f4e79")).join("")}
            ${polyline(payload.trendline_points, s, "#9f3434", 5)}
        </svg>`;

    const polyline = (points, s, color, width) => points.length < 2 ? "" :
        `<polyline fill="none" stroke="${color}" stroke-width="${width}" points="${points.map((p) => `${s.x(p.at)},${s.y(p.quantity)}`).join(" ")}"/>`;

    const dot = (point, s, radius, color) =>
        `<circle cx="${s.x(point.at)}" cy="${s.y(point.quantity)}" r="${radius}" fill="${color}"><title>${point.operation}: ${point.quantity}</title></circle>`;

    const dateLabel = (date) => date.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });

    const formatTrendRate = (trendPerDay) => {
        const dailyRate = Math.abs(trendPerDay);
        const options = [
            ["day", dailyRate],
            ["week", dailyRate * 7],
            ["month", dailyRate * 30],
            ["year", dailyRate * 365],
        ];
        const [unit, value] = options.find(([, rate]) => rate >= 1) || options[options.length - 1];
        return `${formatRate(value)} per ${unit}`;
    };

    const formatRate = (value) => value >= 10 ? value.toFixed(0) : value.toFixed(1);

    document.querySelectorAll("[data-trend-url]").forEach((button) => {
        button.addEventListener("click", () => open(button.dataset.trendUrl).catch(() => {
            chart.innerHTML = '<div class="item-trend-empty">Could not load trend</div>';
        }));
    });
    close.addEventListener("click", () => modal.classList.add("hidden"));
    modal.addEventListener("click", (event) => {
        if (event.target === modal) modal.classList.add("hidden");
    });
})();
