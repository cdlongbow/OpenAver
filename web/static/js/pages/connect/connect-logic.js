// 168b-T6a: connect page pure logic. No DOM, Alpine, window or i18n; returns codes, not copy.

const CONNECTABLE = ['ok', 'patch_diff'];
const KNOWN_KINDS = ['synology', 'linux', 'windows', 'mac'];
const REASON_CODES = ['unreachable', 'timeout', 'tls', 'lan_forbidden', 'not_openaver'];
const BLOCKED_CODES = ['server_old', 'client_old', 'unparseable', 'not_openaver'];

function isConnectableStatus(compat) {
    return !!compat && CONNECTABLE.includes(compat.status);
}

/** The single source of truth for which buttons and fields are enabled (I-U). */
export function connectActions(s) {
    const probe = s.probe || null;
    const fresh = !!probe && typeof s.probedText === 'string' && s.probedText === String(s.urlText || '').trim();
    const live = fresh ? probe : null;
    const ready = s.bridge === 'ready' && !s.busy && !s.restarting;
    const connectable = fresh && probe.ok === true && isConnectableStatus(probe.compat);

    let passwordField = 'hidden';
    if (live && !(live.ok === false && live.reason)) {
        if (!connectable) passwordField = 'disabled';
        else passwordField = live.auth_required === true ? 'input' : 'none';
    }

    const authOk = connectable && (probe.auth_required !== true || probe.authed === true || s.phase === 'authed');
    const canLogin = ready && passwordField === 'input' && typeof s.pin === 'string' && s.pin !== '';
    const changed = String(s.urlText || '').trim() !== String(s.savedUrl || '');
    const canApply = ready && authOk
        && (s.mode === 'local' || (s.mode === 'client' && (changed || s.phase === 'authed')));
    const canSwitchLocal = s.mode === 'client' && ready;
    const canProbe = s.bridge === 'ready' && !s.busy && !s.restarting && String(s.urlText || '').trim() !== '';

    return {
        probeFresh: fresh,
        connectable,
        authOk,
        canProbe,
        passwordField,
        canLogin,
        canApply,
        applyKind: s.mode === 'local' ? 'switch' : 'apply',
        canSwitchLocal,
    };
}

/** connect_probe reply -> code. */
export function probeCode(probe) {
    if (!probe) return 'unreachable';
    const status = probe.compat && probe.compat.status;
    if (probe.ok === false && probe.reason) return REASON_CODES.includes(probe.reason) ? probe.reason : 'unreachable';
    if (status === 'patch_diff' || status === 'server_old' || status === 'client_old' || status === 'unparseable') return status;
    return probe.ok === true ? 'ok' : 'unreachable';
}

/** code -> ok | blocked | unreachable (status dot). */
export function dotState(code) {
    if (code === 'ok' || code === 'patch_diff') return 'ok';
    if (BLOCKED_CODES.includes(code)) return 'blocked';
    return 'unreachable';
}

export function kindCode(kind) {
    return KNOWN_KINDS.includes(kind) ? kind : null;
}

const FORGOT_MAP = {
    synology: 'synology',
    linux: 'linux',
    windows: 'desktop',
    mac: 'desktop',
};

export function forgotCode(kind) {
    return Object.hasOwn(FORGOT_MAP, kind) ? FORGOT_MAP[kind] : null;
}
