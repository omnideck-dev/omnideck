import styles from './PhoneHeader.module.css';

export default function PhoneHeader({ onBack, backLabel = 'Back', title, subtitle, actions }) {
    return (
        <header className={styles.header}>
            <div className={styles.side}>
                {onBack && (
                    <button type="button" className={styles.back} onClick={onBack} data-testid="phone-back">
                        <i className="bi bi-chevron-left" aria-hidden="true" />
                        {backLabel}
                    </button>
                )}
            </div>
            <div className={styles.titles}>
                <h1 className={styles.title} data-testid="phone-title">{title}</h1>
                {subtitle && <div className={styles.subtitle}>{subtitle}</div>}
            </div>
            <div className={`${styles.side} ${styles.actions}`}>{actions}</div>
        </header>
    );
}
