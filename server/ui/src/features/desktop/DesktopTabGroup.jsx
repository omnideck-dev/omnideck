import TabbedPane from '../../components/TabbedPane.jsx';
import { DESKTOP_ACTION_PLACEMENTS } from './desktopViewActions.js';
import styles from './DesktopTabGroup.module.css';

function viewTab(view, actions) {
    return {
        id: view.id,
        testid: view.testid || view.id,
        label: view.label,
        icon: view.iconElement || <i className={`bi ${view.icon || 'bi-window'}`} />,
        menuActions: actions.filter(
            (action) => action.placements.includes(DESKTOP_ACTION_PLACEMENTS.MENU),
        ),
        closable: view.closable,
    };
}

/** Tab chrome for one Desktop tab group; left and right are equivalent. */
export default function DesktopTabGroup({
    tabGroupId,
    tabGroup,
    split,
    onSelectView,
    onCloseView,
    getViewActions,
    fullscreenViewId = null,
}) {
    const tabs = tabGroup.views.map((view) => viewTab(
        view,
        view.id === fullscreenViewId
            ? []
            : getViewActions?.(view, tabGroupId) || [],
    ));

    return (
        <section
            className={styles.tabGroup}
            data-testid={`desktop-tab-group-${tabGroupId}`}
            data-tab-group-id={tabGroupId}
            data-layout={split ? 'split' : 'single'}
        >
            <TabbedPane
                tabs={tabs}
                activeTab={tabGroup.activeViewId}
                onTabChange={(viewId) => onSelectView(tabGroupId, viewId)}
                onCloseTab={(viewId) => onCloseView(tabGroupId, viewId)}
                testIds={{
                    panel: `desktop-tab-group-${tabGroupId}-tabs`,
                    tabBar: `desktop-tab-group-${tabGroupId}-tab-bar`,
                    content: `desktop-tab-group-${tabGroupId}-content-slot`,
                }}
            />
        </section>
    );
}
