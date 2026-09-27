import { describe, expect, it } from 'vitest';
import { appReleaseNotesUrl } from '../appReleaseNotes.js';

describe('appReleaseNotesUrl', () => {
    it.each(['0.2.1', '0.4.0', '0.5.0'])('preserves historical notes for %s', (version) => {
        expect(appReleaseNotesUrl(version)).toBe(
            `https://github.com/omnideck-dev/omnideck/blob/main/docs/releases/app-v${version}.md`,
        );
    });
    it.each(['0.5.1', '0.10.0', '1.0.0'])('opens the app release for %s', (version) => {
        expect(appReleaseNotesUrl(version)).toBe(
            `https://github.com/omnideck-dev/omnideck/releases/tag/app-v${version}`,
        );
    });
    it.each(['', undefined, 'v0.5.1', '0.5.1-beta.1', '0.05.1', '../../main'])('rejects invalid version %s', (version) => {
        expect(appReleaseNotesUrl(version)).toBeNull();
    });
});
