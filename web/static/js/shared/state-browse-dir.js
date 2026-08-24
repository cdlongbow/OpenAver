/**
 * state-browse-dir.js — 共用「選擇資料夾」彈窗 Alpine state mixin（TASK-128-T2）
 *
 * 吃 GET /api/gallery/browse-dir：麵包屑、單擊導覽、上一層、常駐「選取此資料夾」。
 * 三頁（search/settings/scanner）各自 import + mergeState；本檔不得定義 init()（FE-ALPINE-05）。
 */

const BROWSE_DIR_ERR_CODES = new Set([
    'not_found',
    'not_a_directory',
    'permission_denied',
]);

function browseDirStorageKey(targetKey) {
    return 'browse_dir_last_path_' + targetKey;
}

function readLastPath(targetKey) {
    try {
        const v = localStorage.getItem(browseDirStorageKey(targetKey));
        return v == null || v === '' ? null : v;
    } catch {
        return null;
    }
}

function writeLastPath(targetKey, path) {
    try {
        localStorage.setItem(browseDirStorageKey(targetKey), path);
    } catch {
        /* 隱私模式等：記憶失敗不影響選定流程 */
    }
}

function mapBrowseDirError(code) {
    if (code && BROWSE_DIR_ERR_CODES.has(code)) {
        return window.t('common.browse_dir.err_' + code);
    }
    return window.t('common.browse_dir.err_generic');
}

export function browseDirState() {
    return {
        browseDirOpen: false,
        browseDirLoading: false,
        browseDirCurrentPath: '',
        browseDirParentPath: null,
        browseDirEntries: [],
        browseDirError: '',
        browseDirTargetKey: null,
        browseDirExpandVideos: false,
        _browseDirOnSelect: null,
        _browseDirNavGen: 0,

        openBrowseDir(targetKey, onSelect, { expandVideos = false } = {}) {
            this.browseDirTargetKey = targetKey;
            this._browseDirOnSelect = onSelect;
            this.browseDirExpandVideos = !!expandVideos;
            this.browseDirError = '';
            this.browseDirOpen = true;
            const remembered = readLastPath(targetKey);
            this.navigateBrowseDir(remembered);
        },

        closeBrowseDir() {
            this.browseDirOpen = false;
            this._browseDirOnSelect = null;
            this.browseDirError = '';
            this.browseDirEntries = [];
            this.browseDirExpandVideos = false;
        },

        async navigateBrowseDir(path) {
            const gen = ++this._browseDirNavGen;
            this.browseDirLoading = true;
            this.browseDirError = '';
            try {
                let url = '/api/gallery/browse-dir';
                if (path !== null && path !== undefined) {
                    url += '?path=' + encodeURIComponent(path);
                }
                const resp = await fetch(url);
                let json = null;
                try {
                    json = await resp.json();
                } catch {
                    json = null;
                }
                if (gen !== this._browseDirNavGen) return;
                if (!resp.ok) {
                    this.browseDirError = mapBrowseDirError(json && json.error);
                    return;
                }
                this.browseDirCurrentPath = json.current_path;
                this.browseDirParentPath = json.parent_path;
                this.browseDirEntries = Array.isArray(json.entries) ? json.entries : [];
                this.browseDirError = '';
            } catch {
                if (gen !== this._browseDirNavGen) return;
                this.browseDirError = mapBrowseDirError(null);
            } finally {
                if (gen === this._browseDirNavGen) {
                    this.browseDirLoading = false;
                }
            }
        },

        browseDirUp() {
            if (this.browseDirParentPath === null) return;
            this.navigateBrowseDir(this.browseDirParentPath);
        },

        browseDirCanSelect() {
            return !this.browseDirLoading
                && this.browseDirCurrentPath !== ''
                && !this.browseDirError;
        },

        async selectBrowseDir() {
            if (!this.browseDirCanSelect()) return;
            const onSelect = this._browseDirOnSelect;
            const targetKey = this.browseDirTargetKey;
            const currentPath = this.browseDirCurrentPath;
            if (this.browseDirExpandVideos) {
                this.browseDirLoading = true;
                try {
                    const url = '/api/gallery/browse-dir?path='
                        + encodeURIComponent(currentPath)
                        + '&expand=videos';
                    const resp = await fetch(url);
                    let json = null;
                    try {
                        json = await resp.json();
                    } catch {
                        json = null;
                    }
                    if (!resp.ok) {
                        this.browseDirError = mapBrowseDirError(json && json.error);
                        return;
                    }
                    writeLastPath(targetKey, currentPath);
                    if (typeof onSelect === 'function') {
                        onSelect(Array.isArray(json.files) ? json.files : []);
                    }
                    this.closeBrowseDir();
                } catch {
                    this.browseDirError = mapBrowseDirError(null);
                } finally {
                    this.browseDirLoading = false;
                }
                return;
            }
            writeLastPath(targetKey, currentPath);
            if (typeof onSelect === 'function') {
                onSelect(currentPath);
            }
            this.closeBrowseDir();
        },

        browseDirCrumbs() {
            const path = this.browseDirCurrentPath;
            if (path === '') {
                return [{ label: window.t('common.browse_dir.drives'), path: '' }];
            }
            const isWin = /^[A-Za-z]:[\\/]/.test(path);
            if (isWin) {
                const normalized = path.replace(/\//g, '\\');
                const crumbs = [
                    { label: window.t('common.browse_dir.drives'), path: '' },
                ];
                const driveMatch = normalized.match(/^([A-Za-z]:\\)/);
                if (!driveMatch) {
                    return crumbs;
                }
                const drive = driveMatch[1];
                crumbs.push({ label: drive, path: drive });
                const rest = normalized.slice(drive.length);
                if (rest) {
                    let acc = drive.endsWith('\\') ? drive.slice(0, -1) : drive;
                    for (const part of rest.split('\\').filter(Boolean)) {
                        acc = acc + '\\' + part;
                        crumbs.push({ label: part, path: acc });
                    }
                }
                return crumbs;
            }
            if (path === '/') {
                return [{ label: '/', path: '/' }];
            }
            const crumbs = [{ label: '/', path: '/' }];
            let acc = '';
            for (const part of path.split('/').filter(Boolean)) {
                acc = acc + '/' + part;
                crumbs.push({ label: part, path: acc });
            }
            return crumbs;
        },
    };
}
