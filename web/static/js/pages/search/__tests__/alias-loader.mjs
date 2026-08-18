// TASK-106-T2': navigation.js 用瀏覽器 importmap 別名 `@/shared/...`（見
// web/templates/base.html:697 `"@/shared/": "/static/js/shared/"`）plain
// `node --test` 不認得這個別名（無 browser importmap 支援）。這是本次新增
// build-organize-metadata.test.mjs 第一次直接 import navigation.js 才浮現的既有
// infra 缺口（既有 __tests__ 皆未直接 import 過本檔）。
//
// TASK-120-C1：改為逐條鏡射 base.html:699-704 的六個別名
// （`@/shared/`、`@/components/`、`@/showcase/`、`@/scanner/`、`@/settings/`、`@/search/`），
// 裸 `@/` 規則保留在最後當 fallback。既有 `@/shared/` 消費者逐位元不變。
// 只被測試檔用 `module.register()` 掛載（scope 僅該測試檔案的 module graph），
// 不動 package.json test script、不影響其他 __tests__。
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

// 本檔位於 web/static/js/pages/search/__tests__/，上三層即 web/static/js/
const STATIC_JS_ROOT = pathToFileURL(
    path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../../') + '/'
).href;

const ALIASES = [
    ['@/shared/', 'shared/'],
    ['@/components/', 'components/'],
    ['@/showcase/', 'pages/showcase/'],
    ['@/scanner/', 'pages/scanner/'],
    ['@/settings/', 'pages/settings/'],
    ['@/search/', 'pages/search/'],
];

export async function resolve(specifier, context, nextResolve) {
    for (const [prefix, rel] of ALIASES) {
        if (specifier.startsWith(prefix)) {
            return nextResolve(STATIC_JS_ROOT + rel + specifier.slice(prefix.length), context);
        }
    }
    if (specifier.startsWith('@/')) {
        return nextResolve(STATIC_JS_ROOT + specifier.slice(2), context);
    }
    return nextResolve(specifier, context);
}
