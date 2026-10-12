// 168b-T6a: connect page (single standalone Alpine component). All remote I/O goes through the shell bridge.
import { PROBE_ICON_MAP } from '../settings/source-probe-logic.js';
import { connectActions, probeCode, dotState, kindCode, forgotCode } from './connect-logic.js';

export function connectPage() {
    return {
        // --- contract state (read by connect-logic.js) ---
        bridge: 'pending',
        mode: 'local',
        busy: null,
        restarting: false,
        urlText: '',
        savedUrl: '',
        probedText: '',
        probe: null,
        phase: 'idle',
        pin: '',
        // --- free state ---
        localVersion: '',
        savedHost: '',
        savedReach: 'unknown',
        savedVersion: '',
        savedKind: '',
        lastOk: '',
        shellKind: 'windows',
        actionError: '',
        pinError: '',
        moveHintOpen: false,
        _started: false,

        init() {
            const ds = (this.$el && this.$el.dataset) || {};
            this.mode = ds.mode === 'client' ? 'client' : 'local';
            this.shellKind = ds.shellKind === 'mac' ? 'mac' : 'windows';
            const api = window.pywebview && window.pywebview.api;
            if (api && typeof api.connect_get_state === 'function') {
                this.start();
                return;
            }
            window.addEventListener('pywebviewready', () => this.start(), { once: true });
            setTimeout(() => {
                if (this.bridge === 'pending') this.bridge = 'unavailable';
            }, 3000);
        },

        async start() {
            if (this._started) return;
            this._started = true;
            const state = await this.call('connect_get_state');
            if (!state || typeof state.mode !== 'string') {
                this.bridge = 'unavailable';
                return;
            }
            this.mode = state.mode === 'client' ? 'client' : 'local';
            this.localVersion = String(state.version || '');
            this.lastOk = typeof state.last_ok === 'string' ? state.last_ok : '';
            this.savedUrl = this.mode === 'client' ? String(state.url || '') : '';
            this.savedHost = this.mode === 'client' ? String(state.host || '') : '';
            this.urlText = this.savedUrl;
            this.bridge = 'ready';
            if (this.mode === 'client' && this.savedUrl) await this.testConnection();
        },

        async call(name, ...args) {
            const api = window.pywebview && window.pywebview.api;
            if (!api || typeof api[name] !== 'function') return { ok: false, reason: 'no_bridge' };
            let reply;
            try {
                reply = await api[name](...args);
            } catch {
                return { ok: false, reason: 'error' };
            }
            if (reply && reply.reason === 'untrusted') this.bridge = 'unavailable';
            return reply;
        },

        actions() {
            return connectActions(this);
        },

        async testConnection() {
            if (!this.actions().canProbe) return;
            const asked = this.urlText.trim();
            this.busy = 'probe';
            this.phase = 'probing';
            this.actionError = '';
            const reply = await this.call('connect_probe', asked);
            this.busy = null;
            if (this.bridge === 'unavailable') return;
            if (!reply || typeof reply.ok !== 'boolean') {
                this.probe = null;
                this.phase = 'idle';
                this.actionError = 'failed';
                return;
            }
            this.probe = reply;
            this.probedText = asked;
            this.phase = 'probed';
            this.pinError = '';
            if (this.mode === 'client' && asked === this.savedUrl) {
                this.savedReach = dotState(probeCode(reply)) === 'ok' ? 'ok' : 'down';
                this.savedVersion = String(reply.version || '');
                this.savedKind = String(reply.kind || '');
            }
        },

        async login() {
            if (!this.actions().canLogin) return;
            const pin = this.pin;
            const url = this.probe.url;
            this.busy = 'login';
            this.phase = 'logging_in';
            this.actionError = '';
            const reply = await this.call('connect_login', url, pin);
            this.pin = '';
            this.busy = null;
            this.phase = 'probed';
            if (reply && reply.ok === true) this.phase = 'authed';
            this.pinError = reply && reply.ok === true ? '' : (reply && reply.reason) || 'failed';
        },

        // T6b replaces the body; null means the Python side keeps the stored path map.
        pathMapForApply() {
            return null;
        },

        async applyRestart() {
            if (!this.actions().canApply) return;
            this.busy = 'apply';
            this.actionError = '';
            const reply = await this.call('connect_apply_restart', this.probe.url, this.pathMapForApply());
            this.finishRestart(reply);
        },

        async switchLocal() {
            if (!this.actions().canSwitchLocal) return;
            this.busy = 'switch';
            this.actionError = '';
            const reply = await this.call('connect_switch_local_restart');
            this.finishRestart(reply);
        },

        finishRestart(reply) {
            this.busy = null;
            if (reply && reply.ok === true) {
                this.restarting = true;
                return;
            }
            this.actionError = (reply && reply.reason) || 'failed';
        },

        // --- copy ---
        kindLabel(kind) {
            switch (kindCode(kind)) {
                case 'synology': return window.t('connect.kind_synology');
                case 'linux': return window.t('connect.kind_linux');
                case 'windows': return window.t('connect.kind_windows');
                case 'mac': return window.t('connect.kind_mac');
                default: return '';
            }
        },

        versionLine(version, kind) {
            const label = this.kindLabel(kind);
            if (!label) return window.t('connect.version_only', { version });
            return window.t('connect.version_line', { version, kind: label });
        },

        statusLine() {
            if (this.mode === 'local') return window.t('connect.status_local');
            if (this.savedReach === 'down') return window.t('connect.status_down', { host: this.savedHost });
            return window.t('connect.status_connected', { host: this.savedHost });
        },

        statusVersionLine() {
            if (this.mode === 'local') return this.localVersion ? this.versionLine(this.localVersion, '') : '';
            return this.savedVersion ? this.versionLine(this.savedVersion, this.savedKind) : '';
        },

        lastOkText() {
            if (this.mode !== 'client' || !this.lastOk) return '';
            const when = new Date(this.lastOk);
            if (Number.isNaN(when.getTime())) return '';
            return window.t('connect.last_ok', { time: when.toLocaleString() });
        },

        dotName() {
            return this.actions().probeFresh ? dotState(probeCode(this.probe)) : 'unreachable';
        },

        dotIcon() {
            return PROBE_ICON_MAP[this.dotName()];
        },

        resultText() {
            const p = this.probe;
            switch (probeCode(p)) {
                case 'ok': return this.versionLine(p.version, p.kind);
                case 'patch_diff':
                    return window.t('connect.result_patch_diff', { server: p.version, local: this.localVersion });
                case 'server_old': return window.t('connect.result_server_old');
                case 'client_old': return window.t('connect.result_client_old');
                case 'unparseable': return window.t('connect.result_unparseable');
                case 'timeout': return window.t('connect.result_timeout');
                case 'tls': return window.t('connect.result_tls');
                case 'lan_forbidden': return window.t('connect.result_lan_forbidden');
                case 'not_openaver': return window.t('connect.result_not_openaver');
                default: return window.t('connect.result_unreachable');
            }
        },

        resultVersionText() {
            const p = this.probe;
            if (!p || p.ok !== true || probeCode(p) === 'ok') return '';
            return this.versionLine(p.version, p.kind);
        },

        forgotText() {
            switch (forgotCode(this.probe && this.probe.kind)) {
                case 'synology': return window.t('connect.forgot_synology');
                case 'linux': return window.t('connect.forgot_linux');
                case 'desktop': return window.t('connect.forgot_desktop');
                default: return '';
            }
        },

        pinErrorText() {
            if (!this.pinError) return '';
            if (this.pinError === 'bad_pin') return window.t('connect.pin_bad');
            return window.t('connect.pin_failed');
        },

        actionErrorText() {
            return this.actionError ? window.t('connect.error_generic') : '';
        },

        applyLabel() {
            return this.actions().applyKind === 'switch'
                ? window.t('connect.apply_switch')
                : window.t('connect.apply_apply');
        },

        applyHint() {
            return this.mode === 'local'
                ? window.t('connect.apply_hint_local')
                : window.t('connect.apply_hint_client');
        },

        cfText() {
            return this.shellKind === 'mac'
                ? window.t('connect.cf_mac')
                : window.t('connect.cf_windows');
        },
    };
}

document.addEventListener('alpine:init', () => {
    Alpine.data('connectPage', connectPage);
});
