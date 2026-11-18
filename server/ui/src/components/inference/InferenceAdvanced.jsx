import styles from './inference.module.css';
import Select from '../primitives/Select.jsx';
import { conflictingFields, isAvailable, isSupported } from './inferenceConstants.js';

const ADVANCED_HELP = {
    temperature: '0.0 = deterministic, 0.7 = general, 1.0+ = creative',
    top_k: '10 = factual, 40 = general, 100+ = creative',
    top_p: '0.5 = focused, 0.9 = general, 1.0 = everything',
    repeat_penalty: '1.0 = off, 1.1 = general, 1.5+ = strongly discourages repetition',
    context: 'Context window in tokens. Higher = more memory, slower',
    compaction: 'How full the context window gets before old messages are summarized',
    reasoning_effort: 'Higher effort can improve difficult work at the cost of latency and tokens',
    reasoning_summary: 'How much of the model\'s reasoning to show. Auto lets the model decide',
    thinking_budget: 'How many tokens the model can use for reasoning before answering',
};

function formatTokens(tokens) {
    if (!tokens) return null;
    if (tokens >= 1_000_000) return `${Math.round(tokens / 100_000) / 10}M context`;
    if (tokens >= 1_000) return `${Math.round(tokens / 1_000)}K context`;
    return `${tokens} context`;
}

const EFFORT_LABELS = {
    none: 'None',
    minimal: 'Minimal',
    low: 'Low',
    medium: 'Medium',
    high: 'High',
    xhigh: 'Extra high',
    max: 'Maximum',
};

export default function InferenceAdvanced({ draft, capabilities, onChange }) {
    // Setting a field clears the values the model refuses alongside it, and
    // turning thinking on clears the fields thinking turns off.
    const change = (field, value) => {
        onChange(field, value);
        if (value == null || value === false) return;
        const cleared = field === 'think'
            ? capabilities.thinkingExcludedControls || []
            : conflictingFields(field, capabilities);
        for (const other of cleared) {
            if (draft[other] != null) onChange(other, null);
        }
    };
    const thinking = draft.think || capabilities.thinkingRequired;
    const detectedDetails = [
        capabilities.apiLabel,
        formatTokens(capabilities.contextWindow),
    ].filter(Boolean);
    const maxOutputPlaceholder = capabilities.maxOutputTokens
        ? `auto (max ${capabilities.maxOutputTokens.toLocaleString()})`
        : capabilities.api === 'anthropic_messages'
            ? 'auto (16,384 typical)'
            : 'auto';
    const maxOutputMinimum = capabilities.api === 'ollama' ? -1 : 1;
    const maxOutputHelp = capabilities.api === 'ollama'
        ? 'Max tokens per response. Leave empty for the model default; -1 allows unlimited output.'
        : 'Max tokens per response. Leave empty to use the provider default.';
    const hasThinkingLevels = capabilities.thinkingLevels.length > 0;
    const thinkingOptionField = capabilities.thinkingControl;
    const defaultThinkingLevel = capabilities.thinkingDefault;
    const thinkingUsesAutomatic = capabilities.thinkingRequired
        || capabilities.api === 'openai_responses'
        || capabilities.api === 'openai_chat';
    const idleThinkingValue = thinkingUsesAutomatic ? 'automatic' : 'off';
    const thinkingValue = draft.think
        ? draft[thinkingOptionField] || defaultThinkingLevel
        : idleThinkingValue;
    const setThinkingLevel = (value) => {
        if (value === 'off' || value === 'automatic') {
            change('think', value === 'automatic' && capabilities.thinkingRequired ? true : null);
            change(thinkingOptionField, null);
            return;
        }
        change('think', true);
        change(thinkingOptionField, value);
    };

    return (
        <>
            <div className={styles.sectionLabel}>Advanced Settings</div>
            {capabilities.detected ? (
                <div className={styles.detectedCapabilities} data-testid="inference-detection">
                    <i className="bi bi-stars" aria-hidden="true" />
                    <span>Controls detected from {detectedDetails.join(' · ')}</span>
                </div>
            ) : (
                <div className={styles.detectedCapabilities} data-testid="inference-detection">
                    <i className="bi bi-info-circle" aria-hidden="true" />
                    <span>Model settings show once this model&apos;s details are available.</span>
                </div>
            )}
            <div className={styles.advancedBody}>
                    {isAvailable('temperature', capabilities, thinking) && (
                    <div className={styles.advancedField}>
                        <label className={styles.fieldRow}>
                            <span className={styles.fieldLabel}>Temperature</span>
                            <input className={styles.numInput} type="number" data-testid="field-temperature" value={draft.temperature ?? ''} onChange={(e) => change('temperature', e.target.value === '' ? null : Number(e.target.value))} min={0} max={2} step={0.1} placeholder="auto" />
                        </label>
                        <span className={styles.fieldHint}>{ADVANCED_HELP.temperature}</span>
                    </div>
                    )}
                    {isAvailable('top_k', capabilities, thinking) && (
                        <div className={styles.advancedField}>
                            <label className={styles.fieldRow}>
                                <span className={styles.fieldLabel}>Top K</span>
                                <input className={styles.numInput} type="number" data-testid="field-top_k" value={draft.top_k ?? ''} onChange={(e) => change('top_k', e.target.value === '' ? null : Number(e.target.value))} min={0} step={1} placeholder="auto" />
                            </label>
                            <span className={styles.fieldHint}>{ADVANCED_HELP.top_k}</span>
                        </div>
                    )}
                    {isAvailable('top_p', capabilities, thinking) && (
                    <div className={styles.advancedField}>
                        <label className={styles.fieldRow}>
                            <span className={styles.fieldLabel}>Top P</span>
                            <input className={styles.numInput} type="number" data-testid="field-top_p" value={draft.top_p ?? ''} onChange={(e) => change('top_p', e.target.value === '' ? null : Number(e.target.value))} min={0} max={1} step={0.05} placeholder="auto" />
                        </label>
                        <span className={styles.fieldHint}>{ADVANCED_HELP.top_p}</span>
                    </div>
                    )}
                    {isSupported('repeat_penalty', capabilities) && (
                        <div className={styles.advancedField}>
                            <label className={styles.fieldRow}>
                                <span className={styles.fieldLabel}>Repeat Penalty</span>
                                <input className={styles.numInput} type="number" data-testid="field-repeat_penalty" value={draft.repeat_penalty ?? ''} onChange={(e) => change('repeat_penalty', e.target.value === '' ? null : Number(e.target.value))} min={0} step={0.05} placeholder="auto" />
                            </label>
                            <span className={styles.fieldHint}>{ADVANCED_HELP.repeat_penalty}</span>
                        </div>
                    )}
                    {isSupported('context_window', capabilities) && (
                        <div className={styles.advancedField}>
                            <label className={styles.fieldRow}>
                                <span className={styles.fieldLabel}>Runtime Context Window</span>
                                <input className={styles.numInput} type="number" data-testid="field-context_window" value={draft.context_window ?? ''} onChange={(e) => change('context_window', e.target.value === '' ? null : Number(e.target.value))} min={1} placeholder="auto" />
                            </label>
                            <span className={styles.fieldHint}>Sets Ollama’s runtime context allocation. Higher values use more memory.</span>
                        </div>
                    )}
                    {isSupported('num_predict', capabilities) && (
                    <div className={styles.advancedField}>
                        <label className={styles.fieldRow}>
                            <span className={styles.fieldLabel}>Max Output</span>
                            <input className={styles.numInput} type="number" data-testid="field-num_predict" value={draft.num_predict ?? ''} onChange={(e) => change('num_predict', e.target.value === '' ? null : Number(e.target.value))} min={maxOutputMinimum} max={capabilities.maxOutputTokens || undefined} step={1} placeholder={maxOutputPlaceholder} />
                        </label>
                        <span className={styles.fieldHint}>{maxOutputHelp}</span>
                    </div>
                    )}
                    <div className={styles.advancedField} data-testid="field-compaction_threshold">
                        <div className={styles.fieldRow}>
                            <span className={styles.fieldLabel}>Compaction</span>
                            <Select
                                className={styles.selectInput}
                                value={draft.compaction_threshold ?? 0.75}
                                onChange={(value) => change('compaction_threshold', value === 0.75 ? null : Number(value))}
                                ariaLabel="Compaction"
                                testId="compaction-threshold-select"
                                options={[
                                    { value: 0.5, label: '50% — Aggressive' },
                                    { value: 0.65, label: '65% — Early' },
                                    { value: 0.75, label: '75% — Standard' },
                                    { value: 0.85, label: '85% — Late' },
                                    { value: 0.9, label: '90% — Maximum' },
                                ]}
                            />
                        </div>
                        <span className={styles.fieldHint}>{ADVANCED_HELP.compaction}</span>
                    </div>
                    {isSupported('think', capabilities) && hasThinkingLevels && (
                        <div className={styles.advancedField} data-testid="field-thinking-level">
                            <div className={styles.fieldRow}>
                                <span className={styles.fieldLabel}>Thinking Level</span>
                                <Select
                                    className={styles.selectInput}
                                    value={thinkingValue}
                                    onChange={setThinkingLevel}
                                    ariaLabel="Thinking level"
                                    testId="thinking-level-select"
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
                            <span className={styles.fieldHint}>{ADVANCED_HELP.reasoning_effort}</span>
                        </div>
                    )}
                    {draft.think && isSupported('reasoning_summary', capabilities) && (
                        <div className={styles.advancedField} data-testid="field-reasoning_summary">
                            <div className={styles.fieldRow}>
                                <span className={styles.fieldLabel}>Reasoning Summary</span>
                                <Select
                                    className={styles.selectInput}
                                    value={draft.reasoning_summary || 'auto'}
                                    onChange={(value) => change('reasoning_summary', value === 'auto' ? null : value)}
                                    ariaLabel="Reasoning summary"
                                    testId="reasoning-summary-select"
                                    options={[
                                        { value: 'auto', label: 'Auto' },
                                        { value: 'concise', label: 'Concise' },
                                        { value: 'detailed', label: 'Detailed' },
                                    ]}
                                />
                            </div>
                            <span className={styles.fieldHint}>{ADVANCED_HELP.reasoning_summary}</span>
                        </div>
                    )}
            </div>
        </>
    );
}
