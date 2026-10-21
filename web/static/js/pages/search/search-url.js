/**
 * 搜尋 URL 單一出口（173 CD-173-10）
 *
 * 純函式、無 DOM：doSearch／fallbackSearch 只呼叫 buildSearchUrl 組 URL，
 * 名稱一律 encodeURIComponent。keyword REST 的 offset／limit 未給就省略
 * （fallback URL 與既有 /api/search?q=… 逐字相同）；maker REST 恆附 offset。
 */

export const MAKER_PAGE_SIZE = 30;

const enc = encodeURIComponent;

/**
 * @param {object} p
 * @param {boolean} [p.stream] - true ⇒ /api/search/stream，否則 /api/search
 * @param {string} [p.query] - 關鍵字（maker 存在時忽略）
 * @param {{key:string,label:string,spellings?:string[]}|null} [p.maker]
 * @param {number} [p.offset]
 * @param {number} [p.limit]
 * @returns {string}
 */
export function buildSearchUrl({ stream = false, query = '', maker = null, offset, limit } = {}) {
    const params = [];
    if (maker) {
        params.push(`maker_key=${enc(maker.key)}`);
        params.push(`maker=${enc(maker.label)}`);
        for (const s of maker.spellings || []) params.push(`spellings=${enc(s)}`);
    } else {
        params.push(`q=${enc(query)}`);
    }
    if (!stream) {
        if (maker) params.push(`offset=${offset ?? 0}`);
        else if (offset !== undefined) params.push(`offset=${offset}`);
        if (limit !== undefined) params.push(`limit=${limit}`);
    }
    return `${stream ? '/api/search/stream' : '/api/search'}?${params.join('&')}`;
}
