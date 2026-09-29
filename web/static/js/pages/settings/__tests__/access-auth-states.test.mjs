import { test } from 'node:test';
import assert from 'node:assert/strict';
import { register } from 'node:module';
import { pathToFileURL, fileURLToPath } from 'node:url';
import path from 'node:path';

globalThis.window = globalThis;
globalThis.t = (key) => key;

const IMPORTMAP = {
    '@/settings/': 'pages/settings/',
    '@/shared/': 'shared/',
    '@/components/': 'components/',
    '@/search/': 'pages/search/',
    '@/showcase/': 'pages/showcase/',
    '@/scanner/': 'pages/scanner/',
};
const STATIC_JS_ROOT = pathToFileURL(
    path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../../') + '/',
).href;

const loaderCode = `
const IMPORTMAP = ${JSON.stringify(IMPORTMAP)};
const STATIC_JS_ROOT = ${JSON.stringify(STATIC_JS_ROOT)};
export async function resolve(specifier, context, nextResolve) {
    for (const [prefix, rel] of Object.entries(IMPORTMAP)) {
        if (specifier.startsWith(prefix)) {
            return nextResolve(STATIC_JS_ROOT + rel + specifier.slice(prefix.length), context);
        }
    }
    if (specifier.startsWith('@/')) {
        return nextResolve(STATIC_JS_ROOT + specifier.slice(2), context);
    }
    return nextResolve(specifier, context);
}
`;
register(`data:text/javascript,${encodeURIComponent(loaderCode)}`, import.meta.url);

const { stateConfig } = await import('../state-config.js');

function makeFakeThis() {
    return {
        ...stateConfig(),
        serverMode: true,
        accessAuthPin: '1234',
        accessAuthSaving: false,
        _loadFormatVariables: async () => {},
        _loadCoverBadgeRules: async () => {},
        _loadVideoCount: () => {},
        hydrateMetatubeStatus: async () => {},
        loadOllamaModels: () => {},
    };
}

function minimalConfig() {
    return {
        search: {},
        translate: { enabled: false, provider: 'ollama', ollama: {}, gemini: {}, openai: {} },
        scraper: {
            create_folder: true,
            folder_layers: ['{num}'],
            filename_format: '[{num}][{maker}] {title}',
            nfo_title_format: '[{num}]{title}',
            max_title_length: 80,
            max_filename_length: 200,
            video_extensions: ['.mp4'],
            suffix_keywords: [],
            external_manager: 'off',
            download_sample_images: false,
            strm_path_mappings: {},
        },
        gallery: {
            default_mode: 'image', default_sort: 'date', default_order: 'descending',
            items_per_page: 90, min_size_mb: 0, output_dir: '', output_filename: 'gallery_output.html',
            show_table_list: false, cover_badges: { enabled: false, items: {} },
        },
        showcase: { player: '' },
        general: { default_page: 'search', close_action: 'ask', theme: 'light', server_mode: false },
        metatube: { enabled: false },
        sources: [],
    };
}

test('狀態①：enabled=true, can_edit=true → PIN 可用、儲存可用、沒有新提示', () => {
    const fakeThis = makeFakeThis();
    fakeThis.accessAuthEnabled = true;
    fakeThis.accessAuthEnabledSaved = true;
    fakeThis.accessAuthCanEdit = true;
    assert.equal(fakeThis.accessAuthPinDisabled(), false);
    assert.equal(fakeThis.accessAuthSaveDisabled(), false);
    assert.equal(fakeThis.accessAuthStatusHintKey(), '');
});

test('狀態②：enabled=false, can_edit=true → PIN 可用、儲存可用、出現 unset_hint 提示', () => {
    const fakeThis = makeFakeThis();
    fakeThis.accessAuthEnabled = false;
    fakeThis.accessAuthEnabledSaved = false;
    fakeThis.accessAuthCanEdit = true;
    assert.equal(fakeThis.accessAuthPinDisabled(), false);
    assert.equal(fakeThis.accessAuthSaveDisabled(), false);
    assert.equal(fakeThis.accessAuthStatusHintKey(), 'settings.access_auth.unset_hint');
});

test('狀態③：enabled=true, can_edit=false → PIN 鎖定、儲存鎖定、出現 need_login_hint 提示', () => {
    const fakeThis = makeFakeThis();
    fakeThis.accessAuthEnabled = true;
    fakeThis.accessAuthEnabledSaved = true;
    fakeThis.accessAuthCanEdit = false;
    assert.equal(fakeThis.accessAuthPinDisabled(), true);
    assert.equal(fakeThis.accessAuthSaveDisabled(), true);
    assert.equal(fakeThis.accessAuthStatusHintKey(), 'settings.access_auth.need_login_hint');
});

test('狀態④：serverMode=false（桌面單機）→ 不出現任何密碼提示', () => {
    const fakeThis = makeFakeThis();
    fakeThis.serverMode = false;
    fakeThis.accessAuthEnabled = false;
    fakeThis.accessAuthEnabledSaved = false;
    fakeThis.accessAuthCanEdit = true;
    assert.equal(fakeThis.accessAuthPinDisabled(), true);
    assert.equal(fakeThis.accessAuthStatusHintKey(), '');
});

test('loadConfig 讀入 GET 回應的 can_edit 存進 accessAuthCanEdit', async () => {
    const fakeThis = makeFakeThis();
    fakeThis.accessAuthCanEdit = true;
    globalThis.fetch = async (url) => {
        if (url === '/api/access/settings') {
            return { json: async () => ({ success: true, enabled: true, pin: '', pin_revealed: false, can_edit: false }) };
        }
        if (url === '/api/config') {
            return { json: async () => ({ success: true, data: minimalConfig() }) };
        }
        return { json: async () => ({ success: true, data: {} }) };
    };
    await fakeThis.loadConfig.call(fakeThis);
    assert.equal(fakeThis.accessAuthCanEdit, false);
});
