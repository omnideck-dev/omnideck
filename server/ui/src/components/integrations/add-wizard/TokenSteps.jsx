import Button from '../../primitives/Button.jsx';
import Callout from '../../primitives/Callout.jsx';
import styles from './add-wizard.module.css';
import { errorCopy } from './providers.js';
import { Stepper } from './SharedSteps.jsx';

export function ExplainerStep({ onBack, onNext }) {
    return (
        <>
            <Stepper step={1} />
            <div className={styles.wzBody}>
                <h2 className={styles.wzTitle}>Connect an HTTP API</h2>
                <p className={styles.wzSubtitle}>
                    Point your agent at any REST endpoint that authenticates with a
                    {' '}<strong>static token</strong> — an API key or bearer token. You give
                    the base URL and the token; the agent calls paths under it.
                </p>
                <div className={styles.wzContent}>
                    <Callout
                        tone="info"
                        description="Requests are locked to the base URL's host — the agent can't redirect the token to another site."
                    />
                    <div className={styles.chipStack}>
                        <span className={styles.chip}><i className="bi bi-check2" /> Encrypted at rest</span>
                        <span className={styles.chip}><i className="bi bi-check2" /> Agent never reads the token</span>
                        <span className={styles.chip}><i className="bi bi-check2" /> Host-locked to the base URL</span>
                    </div>
                </div>
            </div>
            <div className={styles.footer}>
                <Button onClick={onBack}>
                    <i className="bi bi-arrow-left" /> Back
                </Button>
                <div className={styles.footerRight}>
                    <Button
                        variant="filled"
                        onClick={onNext}
                        data-testid="wizard-next"
                    >
                        Next <i className="bi bi-arrow-right" />
                    </Button>
                </div>
            </div>
        </>
    );
}

export function CredentialsStep({ provider, token, setToken, form, setForm, error, onBack, onCancel, onSubmit }) {
    const canSubmit = token.baseUrl.trim() && token.token.trim();
    return (
        <>
            <Stepper step={2} />
            <div className={styles.wzBodyLeft}>
                <h2 className={styles.wzTitle}>Endpoint &amp; token</h2>
                <p className={styles.wzSubtitle}>
                    All requests resolve against the base URL and are locked to its host.
                </p>
                <div className={styles.wzContent}>
                    <div className={styles.field}>
                        <label className={styles.fieldLabel}>Base URL</label>
                        <input
                            className={styles.input}
                            type="url"
                            placeholder="https://api.example.com"
                            value={token.baseUrl}
                            onChange={(e) => setToken(t => ({ ...t, baseUrl: e.target.value }))}
                            data-testid="wizard-base-url"
                        />
                        <span className={styles.fieldHint}>
                            Requests can only reach this host.
                        </span>
                    </div>

                    <div className={styles.field}>
                        <label className={styles.fieldLabel}>Header name</label>
                        <input
                            className={styles.input}
                            placeholder="Authorization"
                            value={token.headerName}
                            onChange={(e) => setToken(t => ({ ...t, headerName: e.target.value }))}
                            data-testid="wizard-header-name"
                        />
                    </div>

                    <div className={styles.field}>
                        <label className={styles.fieldLabel}>Header value template</label>
                        <input
                            className={`${styles.input} ${styles.inputMono}`}
                            placeholder="Bearer {token}"
                            value={token.headerTemplate}
                            onChange={(e) => setToken(t => ({ ...t, headerTemplate: e.target.value }))}
                            data-testid="wizard-header-template"
                        />
                        <span className={styles.fieldHint}>
                            <code>{'{token}'}</code> is replaced with the secret below.
                        </span>
                    </div>

                    <div className={styles.field}>
                        <label className={styles.fieldLabel}>Token / secret</label>
                        <input
                            className={`${styles.input} ${styles.inputMono}`}
                            type="password"
                            placeholder="paste the token"
                            value={token.token}
                            onChange={(e) => setToken(t => ({ ...t, token: e.target.value }))}
                            data-testid="wizard-token"
                        />
                    </div>

                    <div className={styles.field}>
                        <label className={styles.fieldLabel}>Label (optional)</label>
                        <input
                            className={styles.input}
                            placeholder="Linear · work"
                            value={form.label}
                            onChange={(e) => setForm(f => ({ ...f, label: e.target.value }))}
                            data-testid="wizard-label"
                        />
                        <span className={styles.fieldHint}>
                            How this integration appears in your list, and the basis of its ID.
                        </span>
                    </div>

                    <div className={styles.subsectionLabel}>Permissions</div>
                    <div className={styles.permStack}>
                        <div className={styles.permRow}>
                            <span className={styles.permLabel}>HTTP</span>
                            <select
                                className={styles.accessSelect}
                                value={form.permissions.http || 'r'}
                                onChange={(e) => setForm(f => ({
                                    ...f,
                                    permissions: { ...f.permissions, http: e.target.value },
                                }))}
                                data-testid="wizard-perm-http"
                            >
                                <option value="r">Read only (GET, HEAD)</option>
                                <option value="rw">Read + Write (all methods)</option>
                            </select>
                        </div>
                    </div>
                    <Callout
                        tone="info"
                        description="You can change this later — no need to reconnect."
                    />

                    {error && (() => {
                        const copy = errorCopy(error, provider);
                        return (
                            <Callout
                                tone="danger"
                                title={copy.title}
                                description={copy.description}
                            />
                        );
                    })()}
                </div>
            </div>
            <div className={styles.footer}>
                <Button onClick={onBack}>
                    <i className="bi bi-arrow-left" /> Back
                </Button>
                <div className={styles.footerRight}>
                    <Button onClick={onCancel}>Cancel</Button>
                    <Button
                        variant="filled"
                        disabled={!canSubmit}
                        onClick={onSubmit}
                        data-testid="wizard-submit"
                    >
                        Save <i className="bi bi-check-lg" />
                    </Button>
                </div>
            </div>
        </>
    );
}

export function ConnectingStep() {
    return (
        <>
            <Stepper step={3} />
            <div className={styles.wzBodyLeft}>
                <h2 className={styles.wzTitle}>Saving…</h2>
                <p className={styles.wzSubtitle}>This usually takes a moment.</p>
                <div className={styles.wzContent}>
                    <div className={styles.checkList}>
                        <div className={styles.checkRow}>
                            <div className={`${styles.checkIcon} ${styles.done}`}>
                                <i className="bi bi-check-circle-fill" />
                            </div>
                            <div className={styles.checkLabel}>Securing your token</div>
                            <div className={styles.checkMeta}>done</div>
                        </div>
                        <div className={styles.checkRow}>
                            <div className={`${styles.checkIcon} ${styles.running}`}>
                                <span className={styles.spinner} />
                            </div>
                            <div className={styles.checkLabel}>Starting the connector</div>
                            <div className={styles.checkMeta}>…</div>
                        </div>
                    </div>
                </div>
            </div>
            <div className={styles.footer}>
                <Button disabled>
                    <i className="bi bi-arrow-left" /> Back
                </Button>
                <div className={styles.footerRight}>
                    <Button disabled>Cancel</Button>
                    <Button variant="filled" disabled>Continue</Button>
                </div>
            </div>
        </>
    );
}
