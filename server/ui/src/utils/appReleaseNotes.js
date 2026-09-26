const APP_VERSION = /^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$/;
const REPOSITORY = 'https://github.com/omnideck-dev/omnideck';

export function appReleaseNotesUrl(version) {
    const value = String(version || '');
    if (!APP_VERSION.test(value)) return null;
    const [major, minor, patch] = value.split('.').map(Number);
    // Releases through 0.5.0 predate the app-v* GitHub release records.
    if (major === 0 && (minor < 5 || (minor === 5 && patch === 0))) {
        return `${REPOSITORY}/blob/main/docs/releases/app-v${value}.md`;
    }
    return `${REPOSITORY}/releases/tag/app-v${value}`;
}
