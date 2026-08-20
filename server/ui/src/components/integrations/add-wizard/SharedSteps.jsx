import Button from '../../primitives/Button.jsx';
import styles from './add-wizard.module.css';
import { normalizePathPrefix, PROVIDERS } from './providers.js';

export function ProviderPicker({ onPick, onCancel }) {
    const categories = PROVIDERS.reduce((acc, p) => {
        acc[p.category] = acc[p.category] || [];
        acc[p.category].push(p);
        return acc;
    }, {});

    return (
        <>
            <div className={styles.body}>
                {Object.entries(categories).map(([category, items]) => (
                    <div key={category} className={styles.pickerGroup}>
                        <div className={styles.groupLabel}>{category}</div>
                        <div className={styles.providerGrid}>
                            {items.map(p => (
                                <button
                                    key={p.slug}
                                    className={styles.providerCard}
                                    onClick={() => onPick(p)}
                                    data-testid={`provider-${p.slug}`}
                                >
                                    <div className={styles.providerIcon}>
                                        <i className={`bi ${p.icon}`} />
                                    </div>
                                    <div className={styles.providerInfo}>
                                        <div className={styles.providerTitle}>{p.title}</div>
                                        <div className={styles.providerDesc}>{p.description}</div>
                                    </div>
                                    <i className={`bi bi-chevron-right ${styles.providerChev}`} />
                                </button>
                            ))}
                        </div>
                    </div>
                ))}
            </div>
            <div className={styles.footer}>
                <Button onClick={onCancel}>Cancel</Button>
            </div>
        </>
    );
}

export function Stepper({ step }) {
    const circleClass = (n) => {
        if (step > n) return styles.done;
        if (step === n) return styles.active;
        return '';
    };
    const lineClass = (n) => (step > n ? styles.done : '');
    const circleContent = (n) => (step > n ? <i className="bi bi-check-lg" /> : n);
    return (
        <div className={styles.stepper}>
            <div className={`${styles.stepCircle} ${circleClass(1)}`}>{circleContent(1)}</div>
            <div className={`${styles.stepLine} ${lineClass(1)}`} />
            <div className={`${styles.stepCircle} ${circleClass(2)}`}>{circleContent(2)}</div>
            <div className={`${styles.stepLine} ${lineClass(2)}`} />
            <div className={`${styles.stepCircle} ${circleClass(3)}`}>{circleContent(3)}</div>
        </div>
    );
}

const ACCESS_DISPLAY = { off: 'Off', r: 'Read only', rw: 'Read + Write' };
// CLI has no read/write distinction — the broker exec's the target binary
// with whatever arguments the agent supplies, so "r" (the only reachable
// level; rw is never granted by the CLI catalog entry) means "the agent can
// run it," not "read-only." Reusing the generic Read/Read+Write wording
// here would tell a user connecting a destructive script or a token with
// full write access that it's "Read only," which it isn't.
const CLI_ACCESS_DISPLAY = { off: 'Off', r: 'Enabled', rw: 'Enabled' };
const CAP_DISPLAY = {
    email: 'Email', calendar: 'Calendar', drive: 'Drive', contacts: 'Contacts', cli: 'CLI',
};

function formatPermissions(perms) {
    if (!perms || Object.keys(perms).length === 0) return null;
    return Object.entries(perms)
        .filter(([, v]) => v && v !== 'off')
        .map(([cap, access]) => {
            const display = cap === 'cli' ? CLI_ACCESS_DISPLAY : ACCESS_DISPLAY;
            return `${CAP_DISPLAY[cap] || cap}: ${display[access] || access}`;
        })
        .join(', ');
}

export function SuccessScreen({ provider, form, token, cli, result, onAddAnother, onDone }) {
    const permsSummary = formatPermissions(result.permissions);
    const isToken = provider.authFlow === 'token';
    const isCli = provider.authFlow === 'cli_env';
    const cliScope = cli?.global === false && cli?.pathPrefix
        ? `$HOME/${normalizePathPrefix(cli.pathPrefix)}`
        : 'All sessions';
    return (
        <>
            <Stepper step={4} />
            <div className={styles.wzBodyLeft}>
                <h2 className={styles.wzTitle}>{provider.title} connected</h2>
                <p className={styles.wzSubtitle}>
                    Your agent can now access the capabilities you selected.
                </p>
                <div className={styles.wzContent}>
                    <table className={styles.kvTable}>
                        <tbody>
                            <tr>
                                <td>ID</td>
                                <td>{result.id}</td>
                            </tr>
                            {isCli ? (
                                <tr>
                                    <td>Scope</td>
                                    <td>{cliScope}</td>
                                </tr>
                            ) : (
                                <tr>
                                    <td>{isToken ? 'Base URL' : 'Account'}</td>
                                    <td>{isToken ? token?.baseUrl : form.email}</td>
                                </tr>
                            )}
                            <tr>
                                <td>Label</td>
                                <td>
                                    {form.label
                                        || (isCli
                                            ? provider.title
                                            : isToken
                                                ? `HTTP · ${token?.baseUrl ?? ''}`
                                                : `${provider.title} · ${form.email}`)}
                                </td>
                            </tr>
                            <tr>
                                <td>Permissions</td>
                                <td>{permsSummary || 'Read only'}</td>
                            </tr>
                        </tbody>
                    </table>
                </div>
            </div>
            <div className={styles.footer}>
                <div className={styles.footerRight}>
                    <Button onClick={onAddAnother}>
                        <i className="bi bi-plus-lg" /> Add another
                    </Button>
                    <Button
                        variant="filled"
                        onClick={onDone}
                        data-testid="wizard-done"
                    >
                        Done
                    </Button>
                </div>
            </div>
        </>
    );
}
