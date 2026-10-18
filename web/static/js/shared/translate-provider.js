/**
 * 缺值視為 ollama，與 `pages/settings/state-config.js` 的 `|| 'ollama'` 一致；新增雲端引擎不必改呼叫端
 */
export function isCloudTranslateProvider(provider) {
    return (provider || 'ollama') !== 'ollama';
}
