import CustomAppHost from '../../components/apps/CustomAppHost.jsx';
import styles from './CustomAppSurface.module.css';

/** Content renderer for a Custom App surface; placement belongs to the manager. */
export default function CustomAppSurface({
    surface,
    active,
    actions,
}) {
    return (
        <div
            className={styles.surface}
            data-testid="custom-app-surface"
        >
            <CustomAppHost
                app={surface.app}
                reloadSignal={surface.reloadSignal}
                active={active}
                onOpenChat={() => actions.openChat(surface)}
                onComposeChat={(payload) => actions.composeInChat(surface, payload)}
            />
        </div>
    );
}
