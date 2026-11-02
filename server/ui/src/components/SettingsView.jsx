import { useEffect, useMemo, useState } from 'react';

import { useAppData } from '../contexts/AppData.jsx';
import IntegrationsTab from '../features/integrations/IntegrationsTab.jsx';
import BrandTabs from './primitives/BrandTabs.jsx';
import CustomToolsTab from './CustomToolsTab.jsx';
import MemoryTab from './MemoryTab.jsx';
import ProvidersTab from './providers/ProvidersTab.jsx';
import SkillsTab from './skills/SkillsTab.jsx';
import SystemSettings from './SystemSettings.jsx';
import BrowserProfilesSettings from '../features/browser/BrowserProfilesSettings.jsx';
import styles from './SettingsView.module.css';

// Tab registry — tabs own their own data (via context / their own
// hooks), so adding a new tab is just a row here plus the component.
// `feature` gates visibility on a features.* flag.
const ALL_TABS = [
    { id: 'skills', label: 'Skills', Component: SkillsTab },
    { id: 'providers', label: 'Providers', Component: ProvidersTab },
    { id: 'integrations', label: 'Integrations', Component: IntegrationsTab },
    { id: 'memory', label: 'Memory', Component: MemoryTab },
    { id: 'browser', label: 'Browser', Component: BrowserProfilesSettings },
    { id: 'tools', label: 'Custom Tools', Component: CustomToolsTab, feature: 'custom_tools' },
    { id: 'system', label: 'System', Component: SystemSettings },
];

export default function SettingsView({
    initialTab = 'skills',
}) {
    const { features } = useAppData();
    const tabs = useMemo(
        () => ALL_TABS.filter((t) => !t.feature || features[t.feature]),
        [features],
    );
    const [activeTab, setActiveTab] = useState(initialTab);
    useEffect(() => setActiveTab(initialTab), [initialTab]);
    const active = tabs.find((t) => t.id === activeTab) ?? tabs[0];
    const Active = active.Component;
    return (
        <div className={styles.page} data-testid="settings-page">
            <BrandTabs
                tabs={tabs}
                activeTab={active.id}
                onTabChange={setActiveTab}
                ariaLabel="Settings"
                testIdPrefix="settings-tab"
                idBase="settings"
            />
            <div
                className={styles.content}
                id={`settings-panel-${active.id}`}
                role="tabpanel"
                aria-labelledby={`settings-tab-${active.id}`}
            >
                <Active />
            </div>
        </div>
    );
}
