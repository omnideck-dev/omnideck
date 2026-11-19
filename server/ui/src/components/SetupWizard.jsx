import { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import ModelPicker from './ModelPicker.jsx';
import Select from './primitives/Select.jsx';
import styles from './SetupWizard.module.css';

const STEPS = ['Welcome', 'Provider', 'Main Model', 'Vision Model', 'Ready'];

// Internal provider keys
const PROVIDER_OLLAMA = 'ollama';
const PROVIDER_APERTURE = 'aperture';
const PROVIDER_OPENAI_COMPAT = 'openai-compat';
const PROVIDER_CLOUD = 'cloud';

function ProgressBar({ currentStep }) {
    return (
        <div className={styles.progressBar} role="list" aria-label="Setup progress">
            {STEPS.map((label, i) => {
                const done = i < currentStep;
                const active = i === currentStep;
                return (
                    <div
                        key={label}
                        className={styles.progressStep}
                        role="listitem"
                        aria-label={`${label}${done ? ', completed' : active ? ', current step' : ''}`}
                    >
                        {i > 0 && (
                            <div
                                className={`${styles.progressLine} ${done ? styles.progressLineDone : ''}`}
                                aria-hidden="true"
                            />
                        )}
                        <div
                            className={`${styles.progressCircle} ${active ? styles.progressCircleActive : ''} ${done ? styles.progressCircleDone : ''}`}
                            aria-hidden="true"
                        >
                            {i + 1}
                        </div>
                    </div>
                );
            })}
        </div>
    );
}

function ModelCard({ name, value, description, model, selected, onSelect }) {
    return (
        <button
            className={`${styles.modelCard} ${selected ? styles.modelCardSelected : ''}`}
            onClick={() => onSelect(value ?? name)}
            type="button"
            aria-pressed={selected}
        >
            <span className={`${styles.radio} ${selected ? styles.radioSelected : ''}`} aria-hidden="true" />
            <div className={styles.modelInfo}>
                <span className={styles.modelName}>{name}</span>
                {description && <span className={styles.modelDesc}>{description}</span>}
                {model && (
                    <div className={styles.badges}>
                        {model.parameter_size && (
                            <span className={`${styles.badge} ${styles.badgeParams}`}>
                                {model.parameter_size}
                            </span>
                        )}
                        {model.quantization_level && (
                            <span className={`${styles.badge} ${styles.badgeQuant}`}>
                                {model.quantization_level}
                            </span>
                        )}
                        {model.family && (
                            <span className={`${styles.badge} ${styles.badgeFamily}`}>
                                {model.family}
                            </span>
                        )}
                        {model.is_cloud && (
                            <span className={`${styles.badge} ${styles.badgeCloud}`}>cloud</span>
                        )}
                        {(model.capabilities || []).includes('vision') && (
                            <span className={`${styles.badge} ${styles.badgeVision}`}>vision</span>
                        )}
                    </div>
                )}
            </div>
        </button>
    );
}

// Joins names as "A, B, or C".
const _orList = new Intl.ListFormat('en', { style: 'long', type: 'disjunction' });

export default function SetupWizard({ onComplete, providerCatalog }) {
    const {
        catalog,
        loading: catalogLoading,
        error: catalogError,
        refresh: refreshCatalog,
    } = providerCatalog;
    const [step, setStep] = useState(0);

    // Provider step state
    const [selectedProvider, setSelectedProvider] = useState(null);
    const [cloudChoice, setCloudChoice] = useState(null);
    const [providerUrl, setProviderUrl] = useState('');
    const [providerApiKey, setProviderApiKey] = useState('');
    const [providerError, setProviderError] = useState(null);
    const [providerSaving, setProviderSaving] = useState(false);
    const [ollamaHost, setOllamaHost] = useState('');

    // Model step state. The ModelPicker handles its own list fetching;
    // we just track which model is picked and its metadata (for context_window).
    const [selectedMain, setSelectedMain] = useState(null);
    const [mainModelMeta, setMainModelMeta] = useState(null);
    // undefined = not chosen yet; null = explicit skip; string = model name
    const [selectedVision, setSelectedVision] = useState(undefined);
    const [saving, setSaving] = useState(false);
    const [error, setError] = useState(null);

    const ollamaEntry = catalog.find((c) => c.name === 'ollama');
    const apertureEntry = catalog.find((c) => c.name === 'aperture');
    const compatEntry = catalog.find((c) => c.name === 'openai_compat');
    const cloudEntries = useMemo(() => catalog.filter((c) => c.api_key === 'required'), [catalog]);
    // The first cloud provider stays selected until the user picks another.
    const cloudProvider = cloudChoice ?? cloudEntries[0]?.name ?? null;
    const cloudEntry = cloudEntries.find((c) => c.name === cloudProvider);

    // The provider name as stored in settings / on profiles ('ollama',
    // 'openai_compat', 'anthropic', 'openai', ...).
    const resolvedProviderName = useMemo(() => (
        selectedProvider === PROVIDER_CLOUD
            ? cloudProvider
            : selectedProvider === PROVIDER_APERTURE
                ? 'aperture'
            : selectedProvider === PROVIDER_OPENAI_COMPAT
                ? 'openai_compat'
                : 'ollama'
    ), [selectedProvider, cloudProvider]);
    const resolvedProviderLabel = catalog.find((c) => c.name === resolvedProviderName)?.label
        || resolvedProviderName;

    // Refs for a11y
    const cardRef = useRef(null);
    const stepTitleRef = useRef(null);

    // Focus first element in dialog on mount
    useEffect(() => {
        const first = cardRef.current?.querySelector(
            'button:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])'
        );
        first?.focus();
    }, []);

    // Move focus to step title when step changes
    useEffect(() => {
        stepTitleRef.current?.focus();
    }, [step]);

    // Focus trap: keep Tab/Shift+Tab inside the dialog
    useEffect(() => {
        const handleKeyDown = (e) => {
            if (e.key !== 'Tab' || !cardRef.current) return;
            const focusable = Array.from(cardRef.current.querySelectorAll(
                'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
            ));
            if (focusable.length === 0) return;
            const first = focusable[0];
            const last = focusable[focusable.length - 1];
            if (e.shiftKey) {
                if (document.activeElement === first) { e.preventDefault(); last.focus(); }
            } else {
                if (document.activeElement === last) { e.preventDefault(); first.focus(); }
            }
        };
        document.addEventListener('keydown', handleKeyDown);
        return () => document.removeEventListener('keydown', handleKeyDown);
    }, []);

    useEffect(() => {
        let cancelled = false;

        fetch('/api/setup/defaults')
            .then((res) => (res.ok ? res.json() : {}))
            .then((data) => {
                if (cancelled) return;
                const envHost = typeof data.ollama_host === 'string' ? data.ollama_host.trim() : '';
                setOllamaHost(envHost);
            })
            .catch(() => {
                if (!cancelled) setOllamaHost('');
            });

        return () => { cancelled = true; };
    }, []);

    useEffect(() => {
        if (selectedProvider !== PROVIDER_OLLAMA || !ollamaHost) return;
        setProviderUrl((current) => current.trim() ? current : ollamaHost);
    }, [selectedProvider, ollamaHost]);

    // ── Provider step: create+probe via POST /api/providers ─────────
    // One server-side call. The server picks the storage (direct settings
    // entry vs. brokered vault integration) from the body shape, then
    // probes the new provider — 201 on success, 503 with a message if it
    // can't connect.
    const handleSaveProvider = useCallback(async () => {
        setProviderSaving(true);
        setProviderError(null);

        const body = { name: resolvedProviderName };
        if (selectedProvider === PROVIDER_CLOUD) {
            body.api_key = providerApiKey.trim();
        } else {
            // A blank OpenAI-compatible URL falls back to the catalog's usual local address.
            const endpointUrl = providerUrl.trim()
                || (selectedProvider === PROVIDER_OPENAI_COMPAT ? (compatEntry?.url_hint || '') : '');
            if (!endpointUrl) {
                setProviderError(
                    selectedProvider === PROVIDER_APERTURE
                        ? 'Enter your Aperture gateway URL to continue.'
                        : selectedProvider === PROVIDER_OLLAMA
                            ? 'Enter your Ollama server URL to continue.'
                            : 'Enter your server URL to continue.'
                );
                setProviderSaving(false);
                return;
            }
            body.base_url = endpointUrl;
            if (selectedProvider === PROVIDER_OPENAI_COMPAT && providerApiKey.trim()) {
                body.api_key = providerApiKey.trim();
            }
        }

        try {
            const res = await fetch('/api/providers', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body),
            });
            const data = await res.json().catch(() => ({}));
            if (!res.ok) {
                const message = data.message || data.error || `Failed to connect (${res.status})`;
                if (body.base_url && !message.includes(body.base_url)) {
                    setProviderError(`${message} Tried ${body.base_url}.`);
                } else {
                    setProviderError(message);
                }
                return;
            }
            setStep((s) => s + 1);
        } catch (err) {
            if (body.base_url) {
                setProviderError(`${err.message} Tried ${body.base_url}.`);
            } else {
                setProviderError(err.message);
            }
        } finally {
            setProviderSaving(false);
        }
    }, [selectedProvider, resolvedProviderName, compatEntry, providerUrl, providerApiKey]);

    // ── Final save: server-side orchestration ───────────────────────
    const handleFinish = useCallback(async () => {
        setSaving(true);
        setError(null);
        try {
            const res = await fetch('/api/setup/complete', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    provider: resolvedProviderName,
                    main_model: selectedMain,
                    vision_model: selectedVision,
                    context_window: mainModelMeta?.context_window ?? null,
                }),
            });
            if (!res.ok) {
                const data = await res.json().catch(() => ({}));
                setError(data.error || `Setup failed (${res.status})`);
                setSaving(false);
                return;
            }
            // The completion response includes optional first-run domain
            // identities. SetupGate decides how application startup uses them.
            const data = await res.json().catch(() => ({}));
            onComplete(data);
        } catch (err) {
            setError(`Connection error: ${err.message}`);
            setSaving(false);
        }
    }, [selectedMain, selectedVision, mainModelMeta, resolvedProviderName, onComplete]);

    const canContinue =
        step === 0 ||
        (step === 1 && selectedProvider !== null && !providerSaving) ||
        (step === 2 && selectedMain !== null) ||
        (step === 3 && selectedVision !== undefined) ||
        step === 4;

    const handleNext = () => {
        if (step === 1) { handleSaveProvider(); return; }
        if (step === 4) { handleFinish(); return; }
        setStep((s) => s + 1);
    };

    const handleBack = () => {
        if (step === 2) {
            setSelectedMain(null);
            setMainModelMeta(null);
        }
        if (step === 3) {
            setSelectedVision(undefined);
        }
        setStep((s) => s - 1);
    };

    const buttonLabel =
        step === 0 ? 'Get Started'
            : step === 1 ? (providerSaving ? 'Connecting…' : 'Connect')
                : step === 4 ? 'Start Chatting'
                    : 'Continue';

    const stepTitleId = 'wizard-step-title';

    return (
        <div className={styles.overlay}>
            <div
                ref={cardRef}
                className={styles.card}
                role="dialog"
                aria-modal="true"
                aria-labelledby={stepTitleId}
            >
                <ProgressBar currentStep={step} />

                {/* ── Step 0: Welcome ──────────────────────────────────── */}
                {step === 0 && (
                    <div className={styles.stepContent}>
                        <h1
                            id={stepTitleId}
                            ref={stepTitleRef}
                            className={styles.title}
                            tabIndex={-1}
                        >
                            Welcome to Omnideck
                        </h1>
                        <p className={styles.subtitle}>
                            Let's get you set up. We'll connect to your LLM provider, then
                            pick a main model and an optional vision model.
                        </p>
                    </div>
                )}

                {/* ── Step 1: Provider ─────────────────────────────────── */}
                {step === 1 && (
                    <div className={styles.stepContent}>
                        <h1
                            id={stepTitleId}
                            ref={stepTitleRef}
                            className={styles.title}
                            tabIndex={-1}
                        >
                            Choose your LLM provider
                        </h1>
                        <p className={styles.subtitle}>
                            Connect to a local model server or a cloud API.
                        </p>

                        {catalog.length === 0 && catalogError ? (
                            <>
                                <div className={styles.providerError} role="alert">
                                    Couldn't load providers. {catalogError}
                                </div>
                                <button type="button" className={styles.skipBtn} onClick={refreshCatalog}>
                                    Try again
                                </button>
                            </>
                        ) : catalog.length === 0 && catalogLoading ? (
                            <p className={styles.subtitle}>Loading providers…</p>
                        ) : (
                            <div className={styles.modelList}>
                                {[
                                    ollamaEntry && { key: PROVIDER_OLLAMA, entry: ollamaEntry },
                                    apertureEntry && { key: PROVIDER_APERTURE, entry: apertureEntry },
                                    compatEntry && { key: PROVIDER_OPENAI_COMPAT, entry: compatEntry },
                                    cloudEntries.length > 0 && {
                                        key: PROVIDER_CLOUD,
                                        entry: {
                                            label: 'Cloud API',
                                            description: _orList.format(cloudEntries.map((c) => c.label)),
                                        },
                                    },
                                ].filter(Boolean).map(({ key, entry }) => (
                                    <ModelCard
                                        key={key}
                                        name={entry.label}
                                        value={key}
                                        description={entry.description}
                                        selected={selectedProvider === key}
                                        onSelect={(k) => { setSelectedProvider(k); setProviderError(null); }}
                                    />
                                ))}
                            </div>
                        )}

                        {/* Conditional fields */}
                        {selectedProvider === PROVIDER_OLLAMA && (
                            <div className={styles.providerFields}>
                                <div className={styles.field}>
                                    <label htmlFor="ollama-url" className={styles.fieldLabel}>
                                        Ollama URL
                                    </label>
                                    <input
                                        id="ollama-url"
                                        type="url"
                                        className={styles.fieldInput}
                                        value={providerUrl}
                                        onChange={(e) => setProviderUrl(e.target.value)}
                                        placeholder={ollamaHost || 'Enter your Ollama server URL'}
                                        aria-describedby="ollama-url-hint"
                                    />
                                    <div id="ollama-url-hint" className={styles.fieldHint}>
                                        {ollamaHost
                                            ? 'Detected automatically.'
                                            : 'Enter the address of your Ollama server.'}
                                    </div>
                                </div>
                            </div>
                        )}

                        {selectedProvider === PROVIDER_APERTURE && (
                            <div className={styles.providerFields}>
                                <div className={styles.field}>
                                    <label htmlFor="aperture-url" className={styles.fieldLabel}>
                                        Gateway URL
                                    </label>
                                    <input
                                        id="aperture-url"
                                        type="url"
                                        className={styles.fieldInput}
                                        value={providerUrl}
                                        onChange={(e) => setProviderUrl(e.target.value)}
                                        placeholder="http://aperture-hostname"
                                        aria-describedby="aperture-url-hint"
                                    />
                                    <div id="aperture-url-hint" className={styles.fieldHint}>
                                        No API key needed. Tailscale provides identity; Omnideck discovers
                                        granted models it can use and selects the API format automatically.
                                    </div>
                                </div>
                            </div>
                        )}

                        {selectedProvider === PROVIDER_OPENAI_COMPAT && (
                            <div className={styles.providerFields}>
                                <div className={styles.field}>
                                    <label htmlFor="compat-url" className={styles.fieldLabel}>
                                        Server URL
                                    </label>
                                    <input
                                        id="compat-url"
                                        type="url"
                                        className={styles.fieldInput}
                                        value={providerUrl}
                                        onChange={(e) => setProviderUrl(e.target.value)}
                                        placeholder={compatEntry?.url_hint || ''}
                                        aria-describedby="compat-url-hint"
                                    />
                                    <div id="compat-url-hint" className={styles.fieldHint}>
                                        Base URL of your OpenAI-compatible server.
                                    </div>
                                </div>
                                <div className={styles.field}>
                                    <label htmlFor="compat-key" className={styles.fieldLabel}>
                                        API Key <span className={styles.fieldHint}>(optional)</span>
                                    </label>
                                    <input
                                        id="compat-key"
                                        type="password"
                                        className={styles.fieldInput}
                                        value={providerApiKey}
                                        onChange={(e) => setProviderApiKey(e.target.value)}
                                        placeholder="Leave blank if not required"
                                        autoComplete="new-password"
                                    />
                                </div>
                            </div>
                        )}

                        {selectedProvider === PROVIDER_CLOUD && (
                            <div className={styles.providerFields}>
                                <div className={styles.field}>
                                    <label id="cloud-provider-label" htmlFor="cloud-provider" className={styles.fieldLabel}>
                                        Provider
                                    </label>
                                    <Select
                                        id="cloud-provider"
                                        className={styles.cloudSelect}
                                        value={cloudProvider}
                                        onChange={setCloudChoice}
                                        ariaLabelledBy="cloud-provider-label"
                                        options={cloudEntries.map((c) => ({ value: c.name, label: c.label }))}
                                    />
                                </div>
                                <div className={styles.field}>
                                    <label htmlFor="cloud-key" className={styles.fieldLabel}>
                                        API Key
                                    </label>
                                    <input
                                        id="cloud-key"
                                        type="password"
                                        className={styles.fieldInput}
                                        value={providerApiKey}
                                        onChange={(e) => setProviderApiKey(e.target.value)}
                                        placeholder={cloudEntry?.key_hint || ''}
                                        autoComplete="new-password"
                                        aria-describedby="cloud-key-hint"
                                    />
                                    <div id="cloud-key-hint" className={styles.fieldHint}>
                                        Your API key is stored locally and never sent to us.
                                    </div>
                                </div>
                            </div>
                        )}

                        {providerError && (
                            <div className={styles.providerError} role="alert">
                                {providerError}
                            </div>
                        )}
                    </div>
                )}

                {/* ── Step 2: Main Model ───────────────────────────────── */}
                {step === 2 && (
                    <div className={styles.stepContent}>
                        <h1
                            id={stepTitleId}
                            ref={stepTitleRef}
                            className={styles.title}
                            tabIndex={-1}
                        >
                            Choose your main model
                        </h1>
                        <p className={styles.subtitle}>
                            This will be set as the default model for all built-in agent
                            profiles. You can change individual profiles later in Settings.
                        </p>
                        <ModelPicker
                            providers={[{ name: resolvedProviderName, label: resolvedProviderLabel }]}
                            selectedProvider={resolvedProviderName}
                            selectedModel={selectedMain}
                            onSelect={(_p, m, meta) => {
                                setSelectedMain(m);
                                setMainModelMeta(meta);
                            }}
                            placeholder="Choose a main model…"
                            defaultOpen
                            inline
                        />
                    </div>
                )}

                {/* ── Step 3: Vision Model ─────────────────────────────── */}
                {step === 3 && (
                    <div className={styles.stepContent}>
                        <h1
                            id={stepTitleId}
                            ref={stepTitleRef}
                            className={styles.title}
                            tabIndex={-1}
                        >
                            Choose a vision model
                        </h1>
                        <p className={styles.subtitle}>
                            Used for understanding images and screenshots. Choose a model
                            that supports vision (image input).
                        </p>

                        <ModelPicker
                            providers={[{ name: resolvedProviderName, label: resolvedProviderLabel }]}
                            selectedProvider={resolvedProviderName}
                            selectedModel={selectedVision || null}
                            onSelect={(_p, m) => setSelectedVision(m)}
                            placeholder="Choose a vision model…"
                            capability="vision"
                            defaultOpen
                            inline
                        />

                        <button
                            type="button"
                            className={styles.skipBtn}
                            onClick={() => setSelectedVision(null)}
                        >
                            Skip — I'll configure this later
                        </button>
                    </div>
                )}

                {/* ── Step 4: Ready ────────────────────────────────────── */}
                {step === 4 && (
                    <div className={styles.stepContent}>
                        <div className={styles.stepIcon} aria-hidden="true">&#10003;</div>
                        <h1
                            id={stepTitleId}
                            ref={stepTitleRef}
                            className={styles.title}
                            tabIndex={-1}
                        >
                            You're all set
                        </h1>
                        <div className={styles.summary}>
                            <div className={styles.summaryRow}>
                                <span className={styles.summaryLabel}>Provider</span>
                                <span className={styles.summaryValue}>{resolvedProviderLabel}</span>
                            </div>
                            <div className={styles.summaryRow}>
                                <span className={styles.summaryLabel}>Main model</span>
                                <span className={styles.summaryValue}>{selectedMain}</span>
                            </div>
                            <div className={styles.summaryRow}>
                                <span className={styles.summaryLabel}>Vision model</span>
                                <span className={styles.summaryValue}>
                                    {selectedVision || 'None'}
                                </span>
                            </div>
                        </div>
                    </div>
                )}

                {error && (
                    <div className={styles.error} role="alert">{error}</div>
                )}

                <div className={styles.nav}>
                    {step > 0 && step < 4 && (
                        <button
                            className={styles.backBtn}
                            onClick={handleBack}
                            type="button"
                        >
                            Back
                        </button>
                    )}
                    <button
                        className={styles.nextBtn}
                        onClick={handleNext}
                        disabled={!canContinue || saving}
                        type="button"
                    >
                        {saving ? 'Saving...' : buttonLabel}
                    </button>
                </div>
            </div>
        </div>
    );
}
