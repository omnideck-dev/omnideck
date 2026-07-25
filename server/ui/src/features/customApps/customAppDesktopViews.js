/** Custom Apps owns whether an app slug represents one or many View IDs. */
export function customAppViewId(slug) {
    return `custom-app:${slug}`;
}

export function createCustomAppView(app, reloadSignal = 0) {
    if (!app) return null;
    return {
        id: customAppViewId(app.slug),
        type: 'custom-app',
        identity: {
            appSlug: app.slug,
            navigationTarget: {
                kind: 'custom-app',
                appSlug: app.slug,
            },
        },
        label: app.title,
        icon: app.icon,
        app,
        reloadSignal,
        actions: ['reload'],
        closable: true,
    };
}

export function customAppSlugForView(view) {
    return view?.identity?.appSlug || null;
}
