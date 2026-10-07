export const UPDATE_PREFERENCES_EVENT = 'omnideck:update-preferences';

/** Save the server preference and its startup copy before reporting success. */
export async function saveUpdatePreference(host, key, value, previousValue) {
    if (!host?.setUpdatePreferences) {
        throw new Error('Install the latest desktop application to change update preferences.');
    }
    const response = await fetch('/api/settings', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ [key]: value }),
    });
    if (!response.ok) throw new Error('Could not save update preferences. Please try again.');
    const settings = await response.json();
    try {
        await host.setUpdatePreferences({
            [key === 'software_updates_automatic' ? 'automatic' : 'notify']: value,
        });
    } catch {
        // Do not leave the server's copy to silently reinstate a rejected save
        // at the next scheduled check. The UI keeps the previously saved value.
        try {
            await fetch('/api/settings', {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ [key]: previousValue }),
            });
        } catch {
            // The native copy remains unchanged; the save still reports failure.
        }
        throw new Error('Could not save update preferences on this desktop. Please try again.');
    }
    window.dispatchEvent(new CustomEvent(UPDATE_PREFERENCES_EVENT, { detail: { [key]: value } }));
    return settings;
}
