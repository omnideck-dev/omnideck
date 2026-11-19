// The provider catalog the server sends while Aperture is switched on.
export const PROVIDER_CATALOG = [
    { name: 'ollama', label: 'Ollama', description: 'Run models on your own machine', icon: 'bi-cpu', base_url: 'required', api_key: 'none', key_hint: null, url_hint: null },
    { name: 'aperture', label: 'Tailscale Aperture', description: 'Discover models managed by your organization', icon: 'bi-diagram-3', base_url: 'required', api_key: 'none', key_hint: null, url_hint: null },
    { name: 'openai_compat', label: 'OpenAI-compatible', description: 'vLLM, LM Studio, llama.cpp, etc.', icon: 'bi-hdd-network', base_url: 'required', api_key: 'optional', key_hint: null, url_hint: 'http://localhost:1234/v1' },
    { name: 'anthropic', label: 'Anthropic', description: 'Claude models via API', icon: 'bi-cloud', base_url: 'none', api_key: 'required', key_hint: 'sk-ant-...', url_hint: null },
    { name: 'openai', label: 'OpenAI', description: 'GPT and o-series via API', icon: 'bi-cloud', base_url: 'none', api_key: 'required', key_hint: 'sk-...', url_hint: null },
    { name: 'openrouter', label: 'OpenRouter', description: 'Many providers, one API', icon: 'bi-router', base_url: 'none', api_key: 'required', key_hint: 'sk-or-v1-...', url_hint: null },
];

// The same catalog with Aperture switched off.
export const PROVIDER_CATALOG_WITHOUT_APERTURE = PROVIDER_CATALOG.filter((c) => c.name !== 'aperture');

/** A loaded catalog hook value, as the app data context provides it. */
export function catalogHook(catalog = PROVIDER_CATALOG, overrides = {}) {
    return { catalog, loading: false, error: null, refresh: () => Promise.resolve(catalog), ...overrides };
}
