const PHONE_MAX_SHORT_SIDE = 768;

export function isPhoneDevice() {
    if (!window.matchMedia?.('(pointer: coarse)').matches) return false;
    return Math.min(window.screen.width, window.screen.height) <= PHONE_MAX_SHORT_SIDE;
}
