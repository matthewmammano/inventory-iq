window.buildFuzzySearch = (records, { keys, threshold, ignoreLocation = false }) => {
    if (typeof Fuse !== "undefined") {
        return new Fuse(records, { keys, threshold, ignoreLocation, includeScore: true });
    }
    // Vendor Fuse missing: degrade to a case-insensitive substring match over the same fields.
    const fieldNames = keys.map((key) => key.name ?? key);
    const matchText = (record) =>
        fieldNames.map((name) => [record[name] ?? ""].flat().join(" ")).join(" ").toLowerCase();
    return {
        search: (query) => records
            .filter((record) => matchText(record).includes(query.toLowerCase()))
            .map((item) => ({ item, score: 0 })),
    };
};
