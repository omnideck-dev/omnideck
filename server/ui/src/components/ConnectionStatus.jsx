import Badge from './Badge.jsx';
import styles from './ConnectionStatus.module.css';

/** Features map their runtime states to labels and tones; this owns presentation. */
export default function ConnectionStatus({ tone = 'success', children, ...rest }) {
    if (tone === 'success') {
        return <span className={styles.healthy} {...rest}>
            <i className="bi bi-check-lg" aria-hidden="true" />{children}
        </span>;
    }
    return <Badge variant={tone} {...rest}>
        <i className="bi bi-exclamation-circle" aria-hidden="true" /> {children}
    </Badge>;
}
