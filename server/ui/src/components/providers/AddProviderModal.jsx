import { useCallback, useEffect, useRef, useState } from 'react';

import Button from '../primitives/Button.jsx';
import Callout from '../primitives/Callout.jsx';
import Modal from '../primitives/Modal.jsx';
import styles from './AddProviderModal.module.css';

// The picker catalog. Order is intentional: local first, then the managed
// gateway, a generic compatibility option, and branded cloud APIs.
const CATALOG = [
    { name: 'ollama', label: 'Ollama', icon: 'bi-cpu',
      sub: 'Run models on your own machine' },
    { name: 'aperture', label: 'Tailscale Aperture', icon: 'bi-diagram-3',
      sub: 'Discover models managed by your organization' },
    { name: 'openai_compat', label: 'OpenAI-compatible', icon: 'bi-hdd-network',
      sub: 'vLLM, LM Studio, llama.cpp, etc.' },
    { name: 'anthropic', label: 'Anthropic', icon: 'bi-cloud',
      sub: 'Claude models via API' },
    { name: 'openai', label: 'OpenAI', icon: 'bi-cloud',
      sub: 'GPT and o-series via API' },
    { name: 'openrouter', label: 'OpenRouter', icon: 'bi-router',
      sub: 'Many providers, one API' },
];

/**
 * Two-step modal: pick a provider from the catalog, then fill its
 * config form. Submitting POSTs to /api/providers — the server creates
 * the underlying entry (settings.direct_providers or vault integration),
 * probes the new provider, and returns its model list.
 */
export default function AddProviderModal({ existingNames = [], onClose, onAdded }) {
    const [step, setStep] = useState('catalog'); // 'catalog' | 'configure'
    const [picked, setPicked] = useState(null);

    const handlePickAndContinue = useCallback((entry) => {
        setPicked(entry);
        setStep('configure');
    }, []);

    return (
        <Modal
            onClose={onClose}
            width={560}
            labelledBy="add-provider-title"
            className={styles.modal}
            testId="add-provider-modal"
        >
            {step === 'catalog' && (
                <CatalogStep
                    existingNames={existingNames}
                    onClose={onClose}
                    onPick={handlePickAndContinue}
                />
            )}
            {step === 'configure' && picked && (
                <ConfigureStep
                    entry={picked}
                    onBack={() => setStep('catalog')}
                    onClose={onClose}
                    onAdded={onAdded}
                />
            )}
        </Modal>
    );
}


/* ── Step 1: catalog ───────────────────────────────────────────────── */

function CatalogStep({ existingNames, onClose, onPick }) {
    const [selected, setSelected] = useState(null);
    const available = CATALOG.filter(c => !existingNames.includes(c.name));
    return (
        <>
            <div className={styles.header}>
                <div id="add-provider-title" className={styles.title}>Add a provider</div>
                <button type="button" className={styles.iconBtn} onClick={onClose} aria-label="Close">
                    <i className="bi bi-x-lg" />
                </button>
            </div>
            <div className={styles.body}>
                {available.length === 0 ? (
                    <Callout
                        tone="info"
                        title="All providers configured"
                        description="There's nothing left to add — each provider can be configured once."
                    />
                ) : (
                    <div className={styles.catalogGrid}>
                        {available.map((c) => (
                            <button
                                key={c.name}
                                type="button"
                                className={`${styles.catalogCard} ${selected === c.name ? styles.catalogCardSelected : ''}`}
                                onClick={() => setSelected(c.name)}
                                onDoubleClick={() => onPick(c)}
                                data-testid={`provider-catalog-card-${c.name}`}
                            >
                                <div className={styles.catalogIcon}>
                                    <i className={`bi ${c.icon}`} />
                                </div>
                                <div className={styles.catalogText}>
                                    <div className={styles.catalogName}>{c.label}</div>
                                    <div className={styles.catalogSub}>{c.sub}</div>
                                </div>
                            </button>
                        ))}
                    </div>
                )}
            </div>
            <div className={styles.footer}>
                <Button variant="ghost" onClick={onClose}>Cancel</Button>
                <Button
                    variant="filled"
                    onClick={() => {
                        const entry = available.find(c => c.name === selected);
                        if (entry) onPick(entry);
                    }}
                    disabled={!selected}
                    data-testid="provider-catalog-continue-btn"
                >
                    Continue
                </Button>
            </div>
        </>
    );
}


/* ── Step 2: configure ─────────────────────────────────────────────── */

function ConfigureStep({ entry, onBack, onClose, onAdded }) {
    // Field shape per provider:
    //   ollama          → base_url
    //   aperture        → gateway base_url; auth and API formats are discovered
    //   openai_compat   → base_url, optional api_key
    //   anthropic/openai/openrouter → api_key
    const isOllama = entry.name === 'ollama';
    const isAperture = entry.name === 'aperture';
    const isCompat = entry.name === 'openai_compat';
    const isEndpoint = isOllama || isAperture || isCompat;
    const isCloud = !isEndpoint;

    const [baseUrl, setBaseUrl] = useState('');
    const [ollamaHost, setOllamaHost] = useState('');
    const [apiKey, setApiKey] = useState('');
    const [submitting, setSubmitting] = useState(false);
    const [error, setError] = useState(null);
    const keyRef = useRef(null);
    const urlRef = useRef(null);

    useEffect(() => {
        // Focus the most-likely-to-be-filled field on mount.
        if (isCloud) keyRef.current?.focus();
        else urlRef.current?.focus();
    }, [isCloud]);

    // Prefill the Ollama URL from the host detected at install time, so the
    // user doesn't have to guess it from their container runtime.
    useEffect(() => {
        if (!isOllama) return;
        let cancelled = false;
        fetch('/api/setup/defaults')
            .then((res) => (res.ok ? res.json() : {}))
            .then((data) => {
                if (cancelled) return;
                const envHost = typeof data.ollama_host === 'string' ? data.ollama_host.trim() : '';
                setOllamaHost(envHost);
                if (envHost) setBaseUrl((current) => current.trim() ? current : envHost);
            })
            .catch(() => {});
        return () => { cancelled = true; };
    }, [isOllama]);

    const canSubmit = (() => {
        if (isEndpoint) return !!baseUrl.trim();
        return !!apiKey.trim();
    })();

    const handleSubmit = useCallback(async () => {
        if (!canSubmit || submitting) return;
        setSubmitting(true);
        setError(null);
        const body = { name: entry.name };
        if (isEndpoint) body.base_url = baseUrl.trim();
        if ((isCloud || isCompat) && apiKey.trim()) body.api_key = apiKey.trim();
        try {
            const resp = await fetch('/api/providers', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body),
            });
            const data = await resp.json().catch(() => ({}));
            if (!resp.ok) {
                const message = data.message || data.error || `HTTP ${resp.status}`;
                setError(
                    (isOllama || isAperture) && body.base_url && !message.includes(body.base_url)
                        ? `${message} Tried ${body.base_url}.`
                        : message,
                );
                return;
            }
            onAdded?.(data.provider);
        } catch (err) {
            const message = err?.message || 'Request failed';
            setError((isOllama || isAperture) && body.base_url ? `${message} Tried ${body.base_url}.` : message);
        } finally {
            setSubmitting(false);
        }
    }, [entry.name, isOllama, isAperture, isCompat, isEndpoint, isCloud, baseUrl, apiKey, canSubmit, submitting, onAdded]);

    return (
        <>
            <div className={styles.header}>
                <div className={styles.headerLeft}>
                    <button type="button" className={styles.iconBtn} onClick={onBack} aria-label="Back">
                        <i className="bi bi-arrow-left" />
                    </button>
                    <div id="add-provider-title" className={styles.title}>
                        Configure {entry.label}
                    </div>
                </div>
                <button type="button" className={styles.iconBtn} onClick={onClose} aria-label="Close">
                    <i className="bi bi-x-lg" />
                </button>
            </div>
            <div className={styles.body}>
                {isCloud && (
                    <Callout
                        tone="info"
                        icon="bi-shield-lock"
                        description="Your API key is stored encrypted. Agents reach the provider through a separate broker process — the key never leaves the vault."
                    />
                )}
                {isAperture && (
                    <Callout
                        tone="info"
                        icon="bi-shield-check"
                        title="Tailscale handles access"
                        description="No API key is needed. Omnideck discovers granted models it can use and selects the API format automatically."
                    />
                )}
                {error && (
                    <Callout tone="danger" title="Couldn't add provider" description={error} />
                )}
                {isEndpoint && (
                    <div className={styles.formRow}>
                        <label className={styles.formLabel} htmlFor="provider-url">
                            {isAperture ? 'Gateway URL' : 'Base URL'}
                        </label>
                        <input
                            id="provider-url"
                            ref={urlRef}
                            className={`${styles.input} ${styles.inputMono}`}
                            type="text"
                            value={baseUrl}
                            placeholder={isOllama
                                ? (ollamaHost || 'Enter your Ollama server URL')
                                : isAperture
                                    ? 'http://aperture-hostname'
                                    : 'http://host:port/v1'}
                            onChange={(e) => setBaseUrl(e.target.value)}
                            autoComplete="off"
                        />
                        <div className={styles.formHint}>
                            {isOllama
                                ? (ollamaHost ? 'Detected automatically.' : 'Enter the address of your Ollama server.')
                                : isAperture
                                    ? 'Use the gateway root. Omnideck adds /v1 or /bedrock automatically.'
                                : 'The OpenAI-compatible endpoint URL (include /v1 if your server uses it).'}
                        </div>
                    </div>
                )}
                {(isCloud || isCompat) && (
                    <div className={styles.formRow}>
                        <label className={styles.formLabel} htmlFor="provider-key">
                            API Key{isCompat ? ' (optional)' : ''}
                        </label>
                        <input
                            id="provider-key"
                            ref={keyRef}
                            className={`${styles.input} ${styles.inputMono}`}
                            type="password"
                            value={apiKey}
                            placeholder={_keyPlaceholder(entry.name)}
                            onChange={(e) => setApiKey(e.target.value)}
                            autoComplete="new-password"
                        />
                        {isCompat && (
                            <div className={styles.formHint}>
                                Leave blank if the endpoint doesn't require auth.
                            </div>
                        )}
                    </div>
                )}
            </div>
            <div className={styles.footer}>
                <Button variant="ghost" onClick={onClose}>Cancel</Button>
                <Button
                    variant="filled"
                    onClick={handleSubmit}
                    disabled={!canSubmit || submitting}
                    data-testid="provider-configure-submit-btn"
                >
                    {submitting ? (
                        <><i className="bi bi-broadcast" /> Testing…</>
                    ) : isAperture ? (
                        <><i className="bi bi-broadcast" /> Discover &amp; add</>
                    ) : (
                        <><i className="bi bi-broadcast" /> Test &amp; add</>
                    )}
                </Button>
            </div>
        </>
    );
}


function _keyPlaceholder(name) {
    if (name === 'anthropic') return 'sk-ant-...';
    if (name === 'openai') return 'sk-...';
    if (name === 'openrouter') return 'sk-or-v1-...';
    return '';
}
