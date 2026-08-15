/** Custom Apps owns whether an app slug represents one or many View IDs. */
export function customAppViewId(slug) {
    return `custom-app:${slug}`;
}

export function createCustomAppView(app, reloadSignal = 0, pinnedToSidebar = false) {
    if (!app) return null;
    const id = customAppViewId(app.slug);
    return {
        id,
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
        pinnedToSidebar,
        actions: [
            {
                id: 'toggle-sidebar-pin',
                label: pinnedToSidebar ? 'Unpin from sidebar' : 'Pin to sidebar',
                ariaLabel: pinnedToSidebar
                    ? `Unpin ${app.title} from sidebar`
                    : `Pin ${app.title} to sidebar`,
                icon: pinnedToSidebar ? 'bi-pin-angle-fill' : 'bi-pin-angle',
                testid: `pin-view-${id}`,
            },
            {
                id: 'reload',
                label: 'Reload',
                ariaLabel: `Reload ${app.title}`,
                icon: 'bi-arrow-clockwise',
                testid: `reload-view-${id}`,
            },
        ],
        closable: true,
    };
}

export function customAppSlugForView(view) {
    return view?.identity?.appSlug || null;
}
