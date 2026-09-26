import styles from './inference.module.css';
import { INFERENCE_FIELDS, THINKING_DEFAULTS, isSupported } from './inferenceConstants.js';

const PRESETS = {
    balanced: {
        _default: { temperature: 0.7 },
    },
    creative: {
        _default: { temperature: 1.0, top_p: 0.95 },
    },
    precise: {
        _default: { temperature: 0.2, top_k: 40 },
    },
    code: {
        _default:      { temperature: 0.3, think: true },
        anthropic:     { temperature: 1.0, think: true, thinking_budget: 'standard' },
        anthropic_messages: { temperature: 1.0, think: true, thinking_budget: 'standard' },
        bedrock_model_invoke: { think: true, thinking_budget: 'standard' },
    },
};

function capabilityKey(capabilities) {
    return typeof capabilities === 'object'
        ? capabilities.api || capabilities.provider
        : capabilities;
}

function getPresetHint(presetId, capabilities) {
    const values = resolvePreset(presetId, capabilities) || {};
    const hints = [];
    if (values.temperature != null) hints.push(`${values.temperature} temp`);
    if (values.top_p != null) hints.push(`${values.top_p} top_p`);
    if (values.top_k != null) hints.push(`${values.top_k} top_k`);
    if (values.think) {
        const level = values.reasoning_effort || values.thinking_budget;
        hints.push(level ? `think ${level}` : 'think');
    }
    return hints.join(', ');
}

const PRESET_IDS = ['balanced', 'creative', 'precise', 'code'];
const PRESET_LABELS = { balanced: 'Balanced', creative: 'Creative', precise: 'Precise', code: 'Code' };

export function resolvePreset(presetId, capabilities) {
    const entry = PRESETS[presetId];
    if (!entry) return null;
    const provider = capabilityKey(capabilities);
    const resolved = { ...(entry[provider] || entry._default) };
    if (presetId === 'code' && typeof capabilities === 'object'
        && isSupported('think', capabilities)) {
        resolved.think = true;
        if (capabilities.thinkingControl === 'reasoning_effort') {
            delete resolved.thinking_budget;
            resolved.reasoning_effort = capabilities.thinkingDefault;
            if (['anthropic_messages', 'bedrock_model_invoke'].includes(capabilities.api)) {
                resolved.temperature = 1;
            }
        } else if (capabilities.thinkingControl === 'thinking_budget') {
            delete resolved.reasoning_effort;
            resolved.thinking_budget = capabilities.thinkingDefault || 'standard';
        }
    }
    if (typeof capabilities !== 'object') return resolved;
    return Object.fromEntries(
        Object.entries(resolved).filter(([field]) => isSupported(field, capabilities)),
    );
}

export function detectPreset(draft, capabilities) {
    for (const id of PRESET_IDS) {
        const fields = resolvePreset(id, capabilities);
        const presetKeys = Object.keys(fields).filter((k) => isSupported(k, capabilities));
        const allMatch = presetKeys.every((k) => {
            let draftVal = draft[k];
            const presetVal = fields[k];
            // Null thinking fields equal their default for comparison
            if ((draftVal == null || draftVal === '') && k in THINKING_DEFAULTS) {
                draftVal = THINKING_DEFAULTS[k];
            }
            if (typeof presetVal === 'boolean') return draftVal === presetVal;
            if (typeof presetVal === 'string') return draftVal === presetVal;
            return Number(draftVal) === presetVal;
        });
        if (!allMatch) continue;

        const otherKeys = INFERENCE_FIELDS
            .filter((k) => isSupported(k, capabilities))
            .filter((k) => !presetKeys.includes(k));
        const othersNull = otherKeys.every((k) => {
            const val = draft[k];
            if (val == null || val === '') return true;
            if (k in THINKING_DEFAULTS) return val === THINKING_DEFAULTS[k];
            return false;
        });
        if (othersNull) return id;
    }
    return null;
}

export default function InferencePresets({ capabilities, activePreset, onApply }) {
    const availablePresets = PRESET_IDS.filter(
        (id) => Object.keys(resolvePreset(id, capabilities) || {}).length > 0,
    );
    if (availablePresets.length === 0) return null;
    return (
        <div className={styles.presetGrid}>
            {availablePresets.map((id) => (
                <button
                    key={id}
                    className={`${styles.presetBtn} ${activePreset === id ? styles.presetActive : ''}`}
                    onClick={() => onApply(id)}
                >
                    <span className={styles.presetLabel}>{PRESET_LABELS[id]}</span>
                    <span className={styles.presetHint}>{getPresetHint(id, capabilities)}</span>
                </button>
            ))}
        </div>
    );
}
