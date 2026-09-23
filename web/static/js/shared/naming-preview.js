// naming-preview.js — 命名預覽純函式（CD-146a-12，settings／search 兩頁共用）。
// 從 pages/settings/chip-editor.js 搬出（不是複製）：stripFolderExcludedTokens／
// normalizeFolderLayers 與 ChipEditor widget 本身無關，是純命名邏輯，属於 shared。
// tokenize／serializeTokens（膠囊序列化）留在 chip-editor.js，與本檔無關。

export function stripFolderExcludedTokens(str, excluded) {
    return String(str).replace(/\{[a-zA-Z]+\}/g, (m) => (excluded.has(m) ? '' : m));
}

export function normalizeFolderLayers(rawLayers, excluded) {
    return rawLayers
        .slice(0, 3)
        .map((v) => stripFolderExcludedTokens(v, excluded))
        .filter((v) => v.trim() !== '');
}

/**
 * 命名預覽（CD-146a-12）：filenameFormat／folderLayerList／formatVariables／createFolder
 * 套 tokens（{name: 顯示值} 無大括號 key）算出預覽路徑字串。
 * 與 state-config.js 原 `_previewWith` 逐位元同邏輯搬移，非重寫。
 *
 * @param {object} p
 * @param {string} p.filenameFormat
 * @param {boolean} p.createFolder
 * @param {string[]} p.folderLayerList  已 trim 的純字串陣列（呼叫端自行從 {id,value}[] 或
 *                                       config.scraper.folder_layers 轉出，本函式不關心來源形狀）
 * @param {Array<{name:string, folder_ok:boolean}>} p.formatVariables
 * @param {Object<string,string>} p.tokens  key 無大括號，如 {num:'SSNI-618', ...}
 * @returns {string}
 */
export function buildNamingPreview({ filenameFormat, createFolder, folderLayerList, formatVariables, tokens }) {
    const applyTokens = (str) => {
        let out = str;
        for (const [key, val] of Object.entries(tokens)) {
            out = out.replace(new RegExp(`\\{${key}\\}`, 'g'), val);
        }
        return out;
    };
    const filenamePreview = applyTokens(filenameFormat || '{num} {title}');
    if (!createFolder) return filenamePreview + '.mp4';
    const folderExcluded = new Set(
        (formatVariables || []).filter(v => v.folder_ok === false).map(v => v.name)
    );
    const folderPreview = normalizeFolderLayers(folderLayerList, folderExcluded)
        .map(applyTokens)
        .join('/');
    const folder = folderPreview ? folderPreview + '/' : '';
    return folder + filenamePreview + '.mp4';
}

/**
 * NFO 標題格式預覽代換（TASK-154b-T4 / CD-154b-11）。
 * 扁平 tokens（key 無大括號）→ 字面代換全部出現次數。
 * JS String.replace(str, val) 只換第一個；這裡用 split/join 換全部。
 *
 * @param {string} template
 * @param {Object<string,string>} tokens
 * @returns {string}
 */
export function formatNfoTitle(template, tokens) {
    let out = String(template ?? '');
    for (const [key, val] of Object.entries(tokens || {})) {
        out = out.split(`{${key}}`).join(val);
    }
    return out;
}

/** 薄包裝：設定頁 NFO 標題預覽。 */
export function buildNfoTitlePreview(nfoTitleFormat, tokens) {
    return formatNfoTitle(nfoTitleFormat, tokens);
}
