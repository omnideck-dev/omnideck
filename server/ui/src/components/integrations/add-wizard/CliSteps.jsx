import Button from '../../primitives/Button.jsx';
import Callout from '../../primitives/Callout.jsx';
import styles from './add-wizard.module.css';
import { errorCopy, normalizePathPrefix } from './providers.js';
import { Stepper } from './SharedSteps.jsx';
import { useCliVarsEditor } from './useCliVarsEditor.js';

export function ExplainerStep({ onBack, onNext }) {
    return (
        <>
            <Stepper step={1} />
            <div className={styles.wzBody}>
                <h2 className={styles.wzTitle}>Connect a CLI command</h2>
                <p className={styles.wzSubtitle}>
                    Give a script or binary its own secrets, injected into its environment
                    only when it runs. The agent tells it what arguments to run with — it
                    never sees the secret values.
                </p>
                <div className={styles.wzContent}>
                    <Callout
                        tone="info"
                        description="The secret lives in a separate, locked-down process. Anything it echoes back is scrubbed before the agent sees it."
                    />
                    <div className={styles.chipStack}>
                        <span className={styles.chip}><i className="bi bi-check2" /> Encrypted at rest</span>
                        <span className={styles.chip}><i className="bi bi-check2" /> Agent never reads the secret</span>
                        <span className={styles.chip}><i className="bi bi-check2" /> Optional folder scope</span>
                    </div>
                </div>
            </div>
            <div className={styles.footer}>
                <Button onClick={onBack}>
                    <i className="bi bi-arrow-left" /> Back
                </Button>
                <div className={styles.footerRight}>
                    <Button variant="filled" onClick={onNext} data-testid="wizard-next">
                        Next <i className="bi bi-arrow-right" />
                    </Button>
                </div>
            </div>
        </>
    );
}

export function CredentialsStep({
    provider, cli, setCli, form, setForm, error, onBack, onCancel, onSubmit,
}) {
    const credentialsFilled = cli.command.trim() && cli.vars.some(v => v.name.trim());
    // Normalize before checking "filled" — a folder field of just slashes
    // (e.g. "///") looks non-blank but normalizes to "", which would
    // otherwise silently fall back to global scope on submit.
    const scopeFilled = cli.global || normalizePathPrefix(cli.pathPrefix);
    const canSubmit = credentialsFilled && scopeFilled;

    const setVars = (updater) => setCli(c => ({ ...c, vars: updater(c.vars) }));
    const { updateVar, addVar, removeVar } = useCliVarsEditor(setVars);

    return (
        <>
            <Stepper step={2} />
            <div className={styles.wzBodyLeft}>
                <h2 className={styles.wzTitle}>Command & secrets</h2>
                <p className={styles.wzSubtitle}>
                    The agent can only run this exact command — it supplies arguments, never the binary.
                </p>
                <div className={styles.wzContent}>
                    <div className={styles.field}>
                        <label className={styles.fieldLabel}>Command</label>
                        <input
                            className={`${styles.input} ${styles.inputMono}`}
                            placeholder="/home/omnideck/integration/slack/bridge/run.sh"
                            value={cli.command}
                            onChange={(e) => setCli(c => ({ ...c, command: e.target.value }))}
                            data-testid="wizard-cli-command"
                        />
                        <span className={styles.fieldHint}>
                            What to run — the binary and any fixed leading args, space-separated.
                            Quote a single argument that contains a space, e.g. "/path/with space/run.sh".
                        </span>
                    </div>

                    <div className={styles.field}>
                        <label className={styles.fieldLabel}>Environment variables</label>
                        {cli.vars.map((v, idx) => (
                            <div key={idx} className={styles.kvEditRow}>
                                <input
                                    className={`${styles.input} ${styles.inputMono}`}
                                    placeholder="SLACK_BOT_TOKEN"
                                    value={v.name}
                                    onChange={(e) => updateVar(idx, 'name', e.target.value.toUpperCase())}
                                    data-testid={`wizard-cli-var-name-${idx}`}
                                />
                                <input
                                    className={`${styles.input} ${styles.inputMono}`}
                                    type="password"
                                    placeholder="value"
                                    value={v.value}
                                    onChange={(e) => updateVar(idx, 'value', e.target.value)}
                                    data-testid={`wizard-cli-var-value-${idx}`}
                                />
                                <button
                                    type="button"
                                    className={styles.kvRemoveBtn}
                                    onClick={() => removeVar(idx)}
                                    aria-label="Remove variable"
                                    disabled={cli.vars.length === 1}
                                >
                                    <i className="bi bi-x-lg" />
                                </button>
                            </div>
                        ))}
                        <button
                            type="button"
                            className={styles.linkBtn}
                            onClick={addVar}
                            data-testid="wizard-cli-add-var"
                        >
                            <i className="bi bi-plus-lg" /> Add variable
                        </button>
                    </div>

                    <div className={styles.subsectionLabel}>Scope</div>
                    <div className={styles.radioStack}>
                        <label className={`${styles.radioCard} ${cli.global ? styles.selected : ''}`}>
                            <input
                                type="radio"
                                name="cli-scope"
                                className={styles.radioInput}
                                checked={cli.global}
                                onChange={() => setCli(c => ({ ...c, global: true }))}
                            />
                            <div className={styles.radioIndicator} />
                            <div className={styles.radioInfo}>
                                <div className={styles.radioTitle}>All sessions</div>
                                <div className={styles.radioDesc}>
                                    Available anywhere the agent runs a command.
                                </div>
                            </div>
                        </label>
                        <label className={`${styles.radioCard} ${!cli.global ? styles.selected : ''}`}>
                            <input
                                type="radio"
                                name="cli-scope"
                                className={styles.radioInput}
                                checked={!cli.global}
                                onChange={() => setCli(c => ({ ...c, global: false }))}
                            />
                            <div className={styles.radioIndicator} />
                            <div className={styles.radioInfo}>
                                <div className={styles.radioTitle}>Restricted to a folder</div>
                                <div className={styles.radioDesc}>
                                    Only usable when the agent's working directory is under this folder.
                                </div>
                            </div>
                        </label>
                    </div>
                    {!cli.global && (
                        <div className={styles.field}>
                            <label className={styles.fieldLabel}>Folder</label>
                            <div className={styles.prefixedInput}>
                                <span className={styles.prefixLabel}>$HOME/</span>
                                <input
                                    className={styles.input}
                                    placeholder="repo"
                                    value={cli.pathPrefix}
                                    onChange={(e) => setCli(c => ({ ...c, pathPrefix: e.target.value }))}
                                    data-testid="wizard-cli-path-prefix"
                                />
                            </div>
                            <span className={styles.fieldHint}>
                                Includes subfolders. Leave off the leading/trailing slash.
                            </span>
                        </div>
                    )}

                    <div className={styles.field}>
                        <label className={styles.fieldLabel}>Label (optional)</label>
                        <input
                            className={styles.input}
                            placeholder="Slack bridge"
                            value={form.label}
                            onChange={(e) => setForm(f => ({ ...f, label: e.target.value }))}
                            data-testid="wizard-label"
                        />
                    </div>

                    {error && (() => {
                        const copy = errorCopy(error, provider);
                        return (
                            <Callout tone="danger" title={copy.title} description={copy.description} />
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
                            <div className={styles.checkLabel}>Securing your secret</div>
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
