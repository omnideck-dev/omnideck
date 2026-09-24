const APP_VERSION = /^\d+\.\d+\.\d+$/;

export function appReleaseNotesUrl(version) {
    const value = String(version || '');
    if (!APP_VERSION.test(value)) return null;
    return `https://github.com/omnideck-dev/omnideck/blob/main/docs/releases/app-v${value}.md`;
}
