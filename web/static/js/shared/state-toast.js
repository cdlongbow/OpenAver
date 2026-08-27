export function toastState() {
    return {
        showToast(msg, type = 'success', duration = 2500) {
            Alpine.store('toast').show(msg, type, duration);
        },
    };
}
