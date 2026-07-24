import styles from './CustomAppLayout.module.css';

/** Full/split layout and full-space chrome for an open Custom App. */
export default function CustomAppLayout({
    visible,
    layout,
    testId = 'custom-app-layout',
    toolbar = null,
    banner = null,
    children,
}) {
    const isFull = visible && layout === 'full';
    return (
        <div
            className={`${styles.layout} ${isFull ? styles.full : styles.split} ${!visible ? styles.hidden : ''}`}
            data-testid={testId}
            data-layout={layout}
            data-visible={visible ? 'true' : 'false'}
        >
            {isFull && toolbar}
            {banner}
            {children}
        </div>
    );
}
