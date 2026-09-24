export function libraryInsightsState() {
    return {
        snapshot: null,
        get totalCount() {
            return this.snapshot?.logicalTitles ?? 0;
        },
        async init() {
            try {
                const resp = await fetch('/api/insights/snapshot');
                if (!resp.ok) {
                    return;
                }
                this.snapshot = await resp.json();
            } catch {
                // 網路層或 JSON 解析失敗時維持 snapshot 為 null，totalCount 回 0
            }
        },
    };
}
