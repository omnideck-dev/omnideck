import AppsView from '../../components/apps/AppsView.jsx';
import { useCustomApps } from './CustomApps.jsx';
import {
    useOpenCustomAppView,
} from './useCustomAppDesktopViews.js';

export default function AppsDesktopView({ tabGroupId }) {
    const customApps = useCustomApps();
    const openApp = useOpenCustomAppView();
    const { catalog } = customApps;

    if (!customApps.enabled) return null;
    return (
        <AppsView
            apps={catalog.apps}
            loading={!catalog.loaded || catalog.loading}
            error={catalog.error}
            onRefresh={catalog.refresh}
            onOpenApp={(app) => openApp(app, tabGroupId)}
        />
    );
}
