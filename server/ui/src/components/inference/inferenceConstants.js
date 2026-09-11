export const INFERENCE_FIELDS = [
    'temperature', 'top_k', 'top_p', 'repeat_penalty',
    'think', 'reasoning_effort', 'reasoning_summary', 'thinking_budget',
];

// Presets intentionally leave output limits alone, but model switches must
// clear every transport-specific value the next model cannot accept.
export const MODEL_OPTION_FIELDS = [...INFERENCE_FIELDS, 'num_predict'];

export const SPECIALIZED_ROLE_OUTPUT_CAPS = {
    vision: 512,
    compaction: 8192,
    title: 50,
};

const COMMON_CONTROLS = [
    'temperature', 'top_p', 'context_window', 'num_predict',
    'max_iterations', 'compaction_threshold',
];

// Provider defaults remain a compatibility fallback for model endpoints that
// do not return rich metadata. Once a ModelInfo includes inference_controls,
// that model-specific list is authoritative.
export const FIELD_SUPPORT = {
    temperature:            ['ollama', 'openai', 'anthropic', 'openai_compat', 'openrouter', 'aperture'],
    top_k:                  ['ollama', 'anthropic'],
    top_p:                  ['ollama', 'openai', 'anthropic', 'openai_compat', 'openrouter', 'aperture'],
    repeat_penalty:         ['ollama'],
    context_window:         ['ollama', 'openai', 'anthropic', 'openai_compat', 'openrouter', 'aperture'],
    num_predict:            ['ollama', 'openai', 'anthropic', 'openai_compat', 'openrouter', 'aperture'],
    max_iterations:         ['ollama', 'openai', 'anthropic', 'openai_compat', 'openrouter', 'aperture'],
    think:                  ['ollama', 'openai', 'anthropic', 'openai_compat', 'openrouter'],
    reasoning_effort:       ['openai', 'openrouter', 'openai_compat'],
    reasoning_summary:      ['openai'],
    thinking_budget:        ['anthropic'],
    compaction_threshold:   ['ollama', 'openai', 'anthropic', 'openai_compat', 'openrouter', 'aperture'],
};

const API_DEFAULT_CONTROLS = {
    ollama: [...COMMON_CONTROLS, 'top_k', 'repeat_penalty', 'think'],
    openai_responses: [...COMMON_CONTROLS, 'think', 'reasoning_effort', 'reasoning_summary'],
    openai_chat: [...COMMON_CONTROLS, 'think', 'reasoning_effort'],
    anthropic_messages: [...COMMON_CONTROLS, 'top_k', 'think', 'thinking_budget'],
    bedrock_model_invoke: [
        'context_window', 'num_predict', 'max_iterations',
        'compaction_threshold', 'think', 'thinking_budget',
    ],
};

const WIRE_API_IDS = {
    Responses: 'openai_responses',
    'Chat Completions': 'openai_chat',
    'Anthropic Messages': 'anthropic_messages',
    'Amazon Bedrock': 'bedrock_model_invoke',
};

const API_LABELS = {
    ollama: 'Ollama',
    openai_responses: 'Responses API',
    openai_chat: 'Chat Completions',
    anthropic_messages: 'Anthropic Messages',
    bedrock_model_invoke: 'Amazon Bedrock',
};

const PROVIDER_APIS = {
    ollama: 'ollama',
    openai: 'openai_responses',
    openai_compat: 'openai_chat',
    openrouter: 'openai_chat',
    anthropic: 'anthropic_messages',
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

function providerControls(provider) {
    return Object.entries(FIELD_SUPPORT)
        .filter(([, providers]) => !providers || providers.includes(provider))
        .map(([field]) => field);
}

/** Resolve the controls for one provider/model pair. */
export function resolveInferenceCapabilities(provider, modelInfo = null) {
    const api = modelInfo?.inference_api
        || WIRE_API_IDS[modelInfo?.wire_api]
        || PROVIDER_APIS[provider]
        || null;

    let controls;
    let detected = false;
    if (Array.isArray(modelInfo?.inference_controls)) {
        controls = modelInfo.inference_controls;
        detected = true;
    } else if (api && API_DEFAULT_CONTROLS[api]) {
        controls = API_DEFAULT_CONTROLS[api];
        detected = Boolean(modelInfo?.inference_api || modelInfo?.wire_api);
        if (modelInfo && modelInfo.supports_thinking === false) {
            controls = controls.filter((field) => ![
                'think', 'reasoning_effort', 'reasoning_summary', 'thinking_budget',
            ].includes(field));
        }
    } else {
        controls = providerControls(provider);
    }

    const thinkingControl = modelInfo?.thinking_control
        || (controls.includes('reasoning_effort') ? 'reasoning_effort' : null)
        || (controls.includes('thinking_budget') ? 'thinking_budget' : null)
        || (controls.includes('think') ? 'toggle' : null);
    let thinkingLevels = modelInfo?.thinking_levels;
    if (!Array.isArray(thinkingLevels) && Array.isArray(modelInfo?.reasoning_efforts)) {
        thinkingLevels = modelInfo.reasoning_efforts;
    }
    // Compatibility fallback for older servers. Model-specific values should
    // arrive in ModelInfo; these are wire-protocol values, not model knowledge.
    if (!Array.isArray(thinkingLevels) && thinkingControl === 'reasoning_effort') {
        thinkingLevels = ['low', 'medium', 'high'];
    }
    if (!Array.isArray(thinkingLevels) && thinkingControl === 'thinking_budget') {
        thinkingLevels = ['minimal', 'standard', 'extended'];
    }
    thinkingLevels ||= [];
    const configuredThinkingDefault = modelInfo?.thinking_default;
    const thinkingDefault = thinkingLevels.includes(configuredThinkingDefault)
        ? configuredThinkingDefault
        : thinkingLevels.includes('medium')
            ? 'medium'
            : thinkingLevels.includes('standard')
                ? 'standard'
                : thinkingLevels[0] || null;

    return {
        provider,
        api,
        apiLabel: modelInfo?.wire_api || API_LABELS[api] || provider,
        controls: [...new Set(controls)],
        thinkingControl,
        thinkingLevels,
        thinkingDefault,
        thinkingRequired: modelInfo?.thinking_required === true,
        // Compatibility alias for components served during a rolling update.
        reasoningEfforts: thinkingLevels,
        detected,
        contextWindow: modelInfo?.context_window ?? null,
        maxOutputTokens: modelInfo?.max_output_tokens ?? null,
        upstreamProvider: modelInfo?.upstream_provider || null,
    };
}

export function isSupported(field, providerOrCapabilities, modelInfo = null) {
    if (providerOrCapabilities && typeof providerOrCapabilities === 'object') {
        return providerOrCapabilities.controls.includes(field);
    }
    return resolveInferenceCapabilities(providerOrCapabilities, modelInfo).controls.includes(field);
}

/** Keep only explicit option overrides accepted by one provider/model pair. */
export function sanitizeInferenceOptions(options, capabilities, { allowContext = false } = {}) {
    const sanitized = Object.fromEntries(Object.entries(options || {}).filter(([key, value]) => {
        if (value == null) return false;
        if (key === 'num_ctx' && !allowContext) return false;
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
    const configurableContext = capabilities.api === 'ollama' && modelInfo?.is_cloud !== true;
    next.context_window = configurableContext
        ? modelInfo?.context_window ?? next.context_window
        : null;
    return next;
}
