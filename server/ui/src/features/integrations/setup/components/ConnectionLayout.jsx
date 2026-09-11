import Button from '../../../../components/primitives/Button.jsx';
import styles from '../IntegrationSetupFlow.module.css';

export function ConnectionFrame({
    title, description, children, footer,
}) {
    return (
        <div className={styles.stepPage}>
            <div className={styles.modalBody}>
                <div className={styles.pageIntro}>
                    <h1>{title}</h1>
                    <p>{description}</p>
                </div>
                <div className={styles.credentialCallout}>
                    <span className={styles.credentialIcon}><i className="bi bi-shield-check" /></span>
                    <span className={styles.credentialCopy}>
                        <strong>Your credentials stay on this device</strong>
                        <span>They are encrypted in omnideck’s local vault.</span>
                    </span>
                </div>
                <div className={styles.connectionCard}>{children}</div>
            </div>
            <div className={styles.stepFooter}>{footer}</div>
        </div>
    );
}

export function ConnectionField({ label, hint, children, wide = false }) {
    return (
        <label className={`${styles.field} ${wide ? styles.wideField : ''}`}>
            <span className={styles.fieldLabel}>{label}</span>
            {children}
            {hint && <span className={styles.fieldHint}>{hint}</span>}
        </label>
    );
}

export function ConnectionActions({
    onBack,
    onSubmit,
    submitting,
    submitDisabled,
    submitLabel,
    busyLabel = 'Connecting…',
}) {
    return (
        <>
            <Button onClick={onBack} disabled={submitting}>
                <i className="bi bi-arrow-left" /> Back
            </Button>
            <Button
                variant="filled"
                onClick={onSubmit}
                disabled={submitDisabled || submitting}
                data-testid="wizard-submit"
            >
                {submitting ? busyLabel : submitLabel}
            </Button>
        </>
    );
}
