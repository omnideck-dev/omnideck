import styles from './SetupInstructions.module.css';

export function ConsoleLink({ href, children, host }) {
    return <a className={styles.consoleLink} href={href} target="_blank" rel="noopener noreferrer">
        <span><i className="bi bi-box-arrow-up-right" /> {children}</span><small>{host}</small>
    </a>;
}

export function SetupStep({ number, title, children }) {
    return <details className={styles.step}>
        <summary><span>{number}</span>{title}<i className="bi bi-chevron-down" aria-hidden="true" /></summary>
        <div className={styles.stepBody}>{children}</div>
    </details>;
}

export default function SetupInstructions({ title, description, children, testId }) {
    return <details className={styles.instructions} data-testid={testId}>
        <summary className={styles.instructionsSummary}>
            <span><strong>{title}</strong><small>{description}</small></span>
            <i className="bi bi-chevron-down" aria-hidden="true" />
        </summary>
        <div>{children}</div>
    </details>;
}
