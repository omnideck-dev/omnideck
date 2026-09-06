import ChevronRightIcon from './icons/ChevronRightIcon';
import ToggleSwitch from './ToggleSwitch.jsx';
import Select from './primitives/Select.jsx';
import { isSupported, SPECIALIZED_ROLE_OUTPUT_CAPS } from './inference';
import styles from './SystemSettings.module.css';

const EFFORT_LABELS = {
    none: 'None',
    minimal: 'Minimal',
    low: 'Low',
    medium: 'Medium',
    high: 'High',
    xhigh: 'Extra high',
    max: 'Maximum',
};

function formatTokens(tokens) {
    if (!tokens) return null;
    if (tokens >= 1_000_000) return `${Math.round(tokens / 100_000) / 10}M`;
    if (tokens >= 1_000) return `${Math.round(tokens / 1_000)}K`;
    return String(tokens);
}

export function ModelDefaultsSummary({ capabilities, role, options = {} }) {
    if (!capabilities?.detected) return null;
    const details = [
        capabilities.upstreamProvider,
        capabilities.apiLabel,
        capabilities.contextWindow && `${formatTokens(capabilities.contextWindow)} context`,
        capabilities.maxOutputTokens && `${formatTokens(capabilities.maxOutputTokens)} max output`,
    ].filter(Boolean);
    const configuredCap = SPECIALIZED_ROLE_OUTPUT_CAPS[role];
    const effectiveCap = capabilities.maxOutputTokens
        ? Math.min(configuredCap, capabilities.maxOutputTokens)
        : configuredCap;
    const explicitOutput = options?.num_predict;
    const outputDetail = explicitOutput != null
        ? `${formatTokens(explicitOutput)} output override`
        : `${formatTokens(effectiveCap)}-token role cap`;
    const hasSamplingOverrides = ['temperature', 'top_k', 'top_p']
        .some((key) => options?.[key] != null);
    return (
        <div className={styles.modelDetection} data-testid={`${role}-model-detection`}>
            <i className="bi bi-stars" aria-hidden="true" />
            <span>{details.join(' · ')} · {hasSamplingOverrides ? 'Custom sampling' : 'Auto sampling'} · {outputDetail}</span>
        </div>
    );
}

export default function SpecializedModelOptions({
    role,
    capabilities,
    options,
    think = false,
    open,
    onToggle,
    onPatch,
}) {
    const optionKey = `${role}_options`;
    const setOption = (key, value) => onPatch({
        [optionKey]: { ...(options || {}), [key]: value },
    });
    const hasThinkingLevels = capabilities.thinkingLevels.length > 0;
    const thinkingOptionField = capabilities.thinkingControl;
    const defaultThinkingLevel = capabilities.thinkingDefault;
    const thinkingUsesAutomatic = capabilities.thinkingRequired
        || capabilities.api === 'openai_responses'
        || capabilities.api === 'openai_chat'
        || (capabilities.api === 'anthropic_messages'
            && thinkingOptionField === 'reasoning_effort')
        || (capabilities.api === 'bedrock_model_invoke'
            && thinkingOptionField === 'reasoning_effort');
    const idleThinkingValue = thinkingUsesAutomatic ? 'automatic' : 'off';
    const thinkingValue = think
        ? options?.[thinkingOptionField] || defaultThinkingLevel
        : idleThinkingValue;
    const setThinkingLevel = (value) => {
        const enabled = value !== 'off'
            && (value !== 'automatic' || capabilities.thinkingRequired);
        onPatch({
            vision_think: enabled,
            [optionKey]: {
                ...(options || {}),
                [thinkingOptionField]: value === 'off' || value === 'automatic' ? null : value,
            },
        });
    };
    const hasOverrides = Object.values(options || {}).some((value) => value != null) || (role === 'vision' && think);
    const allowContext = capabilities.api === 'ollama';
    const fields = [
        { key: 'temperature', control: 'temperature', label: 'Temperature', step: 0.1, min: 0, max: 2 },
        { key: 'top_k', control: 'top_k', label: 'Top K', step: 1, min: 0 },
        { key: 'top_p', control: 'top_p', label: 'Top P', step: 0.05, min: 0, max: 1 },
        ...(allowContext ? [{
            key: 'num_ctx', control: 'context_window',
            label: 'Runtime Context Window',
            step: 1, min: 1,
        }] : []),
        {
            key: 'num_predict', control: 'num_predict', label: 'Max Output', step: 1, min: 1,
            max: capabilities.maxOutputTokens || undefined,
        },
    ].filter(({ control }) => isSupported(control, capabilities));

    return (
        <>
            <ModelDefaultsSummary capabilities={capabilities} role={role} options={options} />
            <button
                type="button"
                className={`${styles.groupDisclosure} ${open ? styles.groupDisclosureOpen : ''}`}
                onClick={onToggle}
                aria-expanded={open}
                data-testid={`${role}-advanced-toggle`}
            >
                <ChevronRightIcon className={styles.chev} />
                Advanced inference
            </button>
            {open && (
                <div className={styles.groupBody} data-testid={`${role}-advanced-panel`}>
                    {role === 'vision' && isSupported('think', capabilities) && hasThinkingLevels && (
                        <div className={styles.groupRow} data-testid="vision-thinking-level">
                            <div className={styles.settingInfo}>
                                <span className={styles.settingTitle}>Thinking Level</span>
                                <span className={styles.settingDesc}>Choose the level supported by this model.</span>
                            </div>
                            <Select
                                className={styles.roleSelect}
                                value={thinkingValue}
                                onChange={setThinkingLevel}
                                ariaLabel="Vision thinking level"
                                options={[
                                    thinkingUsesAutomatic
                                        ? { value: 'automatic', label: 'Automatic' }
                                        : { value: 'off', label: 'Off' },
                                    ...capabilities.thinkingLevels.map((level) => ({
                                        value: level,
                                        label: EFFORT_LABELS[level] || level,
                                    })),
                                ]}
                            />
                        </div>
                    )}
                    {role === 'vision' && isSupported('think', capabilities) && !hasThinkingLevels && (
                        <label className={styles.groupRow} data-testid="vision-think-toggle">
                            <div className={styles.settingInfo}>
                                <span className={styles.settingTitle}>Thinking</span>
                                <span className={styles.settingDesc}>Off by default for fast image analysis.</span>
                            </div>
                            <ToggleSwitch
                                checked={think}
                                onChange={(event) => onPatch({ vision_think: event.target.checked })}
                                aria-label="Thinking"
                            />
                        </label>
                    )}
                    {fields.map(({ key, label, control: _control, ...inputProps }) => (
                        <div key={key} className={styles.groupRow}>
                            <div className={styles.settingInfo}>
                                <span className={styles.settingTitle}>{label}</span>
                                <span className={styles.settingDesc}>
                                    {key === 'num_ctx' && capabilities.contextWindow
                                        ? `Auto uses Ollama’s detected ${formatTokens(capabilities.contextWindow)} context.`
                                        : key === 'num_predict'
                                            ? `Auto uses the ${SPECIALIZED_ROLE_OUTPUT_CAPS[role].toLocaleString()}-token role cap.`
                                            : 'Auto uses the selected model’s default.'}
                                </span>
                            </div>
                            <input
                                className={styles.numberInput}
                                type="number"
                                {...inputProps}
                                value={options?.[key] ?? ''}
                                placeholder="Auto"
                                data-testid={`${role}-option-${key}`}
                                onChange={(event) => {
                                    const raw = event.target.value;
                                    setOption(key, raw === '' ? null : Number(raw));
                                }}
                            />
                        </div>
                    ))}
                    {hasOverrides && (
                        <button
                            type="button"
                            className={styles.resetDefaults}
                            onClick={() => onPatch({
                                [optionKey]: {},
                                ...(role === 'vision' ? { vision_think: false } : {}),
                            })}
                        >
                            Restore automatic defaults
                        </button>
                    )}
                </div>
            )}
        </>
    );
}
