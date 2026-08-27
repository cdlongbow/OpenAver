export function createToastStore() {
    return {
        message: '',
        type: 'success',
        visible: false,
        _timer: null,
        // 逐字保留今日五份實作的共同語意：後到的覆蓋先到的（先取消舊計時器再排新的）
        show(msg, type = 'success', duration = 2500) {
            this.message = msg;
            this.type = type;
            this.visible = true;
            if (this._timer) clearTimeout(this._timer);
            this._timer = setTimeout(() => { this.visible = false; this._timer = null; }, duration);
        },
        hide() {
            if (this._timer) clearTimeout(this._timer);
            this._timer = null;
            this.visible = false;
        },
    };
}

document.addEventListener('alpine:init', () => {
    Alpine.store('toast', createToastStore());
});
