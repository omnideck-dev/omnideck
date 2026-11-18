export const INFERENCE_FIELDS = [
    'temperature', 'top_k', 'top_p', 'repeat_penalty',
    'think', 'reasoning_effort', 'reasoning_summary', 'thinking_budget',
];

// Presets intentionally leave output limits alone, but model switches must
// clear every transport-specific value the next model cannot accept.
export const MODEL_OPTION_FIELDS = [...INFERENCE_FIELDS, 'num_predict'];

const API_LABELS = {
    ollama: 'Ollama',
    openai_responses: 'Responses API',
    openai_chat: 'Chat Completions',
    anthropic_messages: 'Anthropic Messages',
};

export const THINKING_DEFAULTS = {
    reasoning_effort: 'medium',
    reasoning_summary: 'auto',
    thinking_budget: 'standard',
};

const OPTION_CONTROLS = {
    temperature: 'temperature',
    top_k: 'top_k',
    top_p: 'top_p',
    repeat_penalty: 'repeat_penalty',
    num_ctx: 'context_window',
    num_predict: 'num_predict',
    reasoning_effort: 'reasoning_effort',
    reasoning_summary: 'reasoning_summary',
    thinking_budget: 'thinking_budget',
};

/**
 * Resolve the controls for one provider/model pair from the model details the
 * server sends. Without details no model setting is offered, so nothing can
 * be set that the model might refuse.
 */
export function resolveInferenceCapabilities(provider, modelInfo = null) {
    const api = modelInfo?.inference_api || null;
    const controls = [...new Set(modelInfo?.inference_controls || [])];
    const thinkingLevels = modelInfo?.thinking_levels || [];
    const thinkingDefault = thinkingLevels.includes(modelInfo?.thinking_default)
        ? modelInfo.thinking_default
        : thinkingLevels[0] || null;
    return {
        provider,
        api,
        apiLabel: modelInfo?.wire_api || API_LABELS[api] || provider,
        controls,
        thinkingExcludedControls: (modelInfo?.thinking_excluded_controls || [])
            .filter((field) => controls.includes(field)),
        exclusiveControls: (modelInfo?.exclusive_controls || [])
            .map((group) => group.filter((field) => controls.includes(field)))
            .filter((group) => group.length > 1),
        thinkingControl: modelInfo?.thinking_control || null,
        thinkingLevels,
        thinkingDefault,
        thinkingRequired: modelInfo?.thinking_required === true,
        detected: Boolean(modelInfo),
        contextWindow: modelInfo?.context_window ?? null,
        maxOutputTokens: modelInfo?.max_output_tokens ?? null,
    };
}

export function isSupported(field, capabilities) {
    return capabilities.controls.includes(field);
}

/** Whether a field can be set for this model with thinking on or off. */
export function isAvailable(field, capabilities, think) {
    if (!isSupported(field, capabilities)) return false;
    const thinking = Boolean(think) || capabilities.thinkingRequired;
    return !(thinking && (capabilities.thinkingExcludedControls || []).includes(field));
}

/** Fields the model refuses alongside *field*. */
export function conflictingFields(field, capabilities) {
    return (capabilities.exclusiveControls || [])
        .filter((group) => group.includes(field))
        .flat()
        .filter((other) => other !== field);
}

/**
 * Clear values the model would refuse: fields that thinking turns off, and
 * all but the first set field of a group the model refuses together.
 */
export function clearRejectedValues(values, capabilities, think) {
    const next = { ...values };
    for (const field of capabilities.thinkingExcludedControls || []) {
        if (next[field] != null && !isAvailable(field, capabilities, think)) next[field] = null;
    }
    for (const group of capabilities.exclusiveControls || []) {
        const kept = group.find((field) => next[field] != null);
        for (const field of group) {
            if (field !== kept && next[field] != null) next[field] = null;
        }
    }
    return next;
}

/** Keep only explicit option overrides accepted by one provider/model pair. */
export function sanitizeInferenceOptions(options, capabilities, { think = false } = {}) {
    const accepted = clearRejectedValues(options || {}, capabilities, think);
    const sanitized = Object.fromEntries(Object.entries(accepted).filter(([key, value]) => {
        if (value == null) return false;
        const control = OPTION_CONTROLS[key];
        return control && isSupported(control, capabilities);
    }));
    if (sanitized.reasoning_effort
        && capabilities.thinkingControl === 'reasoning_effort'
        && !capabilities.thinkingLevels.includes(sanitized.reasoning_effort)) {
        delete sanitized.reasoning_effort;
    }
    return sanitized;
}

/** Normalize a profile draft after selecting a different provider/model. */
export function sanitizeProfileForModel(profile, capabilities, modelInfo = null) {
    const next = { ...profile };
    for (const field of MODEL_OPTION_FIELDS) {
        if (!isSupported(field, capabilities)) next[field] = null;
    }
    if (next.reasoning_effort
        && capabilities.thinkingControl === 'reasoning_effort'
        && !capabilities.thinkingLevels.includes(next.reasoning_effort)) {
        next.reasoning_effort = null;
    }
    if (capabilities.thinkingRequired) next.think = true;
    next.context_window = isSupported('context_window', capabilities)
        ? modelInfo?.context_window ?? next.context_window
        : null;
    return clearRejectedValues(next, capabilities, next.think);
}
