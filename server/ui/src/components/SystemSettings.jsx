import { useState, useEffect, useCallback } from 'react';
import { useAppData } from '../contexts/AppData.jsx';
import styles from './SystemSettings.module.css';
import ModelPicker from './ModelPicker.jsx';
import PackageIcon from './icons/PackageIcon';
import EyeIcon from './icons/EyeIcon';
import CompactionIcon from './icons/CompactionIcon';
import ToggleSwitch from './ToggleSwitch.jsx';
import ChevronRightIcon from './icons/ChevronRightIcon';
import WrenchIcon from './icons/WrenchIcon.jsx';
import DownloadIcon from './icons/DownloadIcon';
import SparkleIcon from './icons/SparkleIcon';
import SoftwareUpdateStatus from './SoftwareUpdateStatus.jsx';
import { useIsHosted } from '../features/app/OmnideckHost.jsx';

export default function SystemSettings() {
    const { providersHook, refreshFeatures } = useAppData();
    const { providers } = providersHook;
    const [profiles, setProfiles] = useState([]);
    const [settings, setSettings] = useState({ default_agent: 'omnideck' });
    const [loading, setLoading] = useState(true);
    const [visionAdvancedOpen, setVisionAdvancedOpen] = useState(false);
    // Omnideck run from the command line, or opened in a plain browser, has no
    // installer behind it: there is nothing for these settings to act on, and
    // updating is done with the command line tool instead.
    const hosted = useIsHosted();

    useEffect(() => {
        async function init() {
            try {
                const [settingsRes, profilesRes] = await Promise.all([
                    fetch('/api/settings'),
                    fetch('/api/profiles'),
                ]);
                const settingsData = await settingsRes.json();
                const profilesData = await profilesRes.json();
                setSettings(settingsData);
                setProfiles(profilesData);
            } catch {
                // keep defaults on error
            } finally {
                setLoading(false);
            }
        }
        init();
    }, []);

    const updateSetting = useCallback(async (key, value) => {
        const previousValue = settings[key];
        setSettings((prev) => ({ ...prev, [key]: value }));
        try {
            const res = await fetch('/api/settings', {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ [key]: value }),
            });
            if (res.ok) {
                const updated = await res.json();
                setSettings(updated);
                if (key === 'custom_apps_enabled' || key === 'custom_tools_enabled') {
                    await refreshFeatures();
                }
                return;
            }
        } catch {
            // Restore the server-backed value below.
        }
        setSettings((prev) => ({ ...prev, [key]: previousValue }));
    }, [refreshFeatures, settings]);

    // Update a (provider, model) pair atomically so they always stay in sync.
    const updateProviderModel = useCallback(async (providerKey, modelKey, provider, model) => {
        setSettings((prev) => ({ ...prev, [providerKey]: provider || '', [modelKey]: model || '' }));
        try {
            const res = await fetch('/api/settings', {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ [providerKey]: provider || '', [modelKey]: model || '' }),
            });
            if (res.ok) {
                const updated = await res.json();
                setSettings(updated);
            }
        } catch {
            // silent
        }
    }, []);

    // The provider name driving the vision_options field-visibility logic.
    const visionProvider = settings.vision_provider || (providers[0]?.name ?? '');

    if (loading) return null;

    return (
        <div className={styles.container}>
            {/* Updates — only the desktop application can install one, so this
                whole section is absent when Omnideck is run any other way. */}
            {hosted && (
                <>
                    <div className={styles.sectionLabel}>Updates</div>
                    <div className={styles.settingsGroup} data-testid="updates-settings-group">
                        <SoftwareUpdateStatus />

                        <label className={styles.settingRow} data-testid="automatic-updates-toggle">
                            <div className={styles.settingIcon}>
                                <DownloadIcon />
                            </div>
                            <div className={styles.settingInfo}>
                                <span className={styles.settingTitle}>Install updates automatically</span>
                                <span className={styles.settingDesc}>
                                    Updates install the next time you open Omnideck, never while you are working. Turn this off to be asked each time.
                                </span>
                            </div>
                            <ToggleSwitch
                                checked={settings.software_updates_automatic !== false}
                                onChange={(e) => updateSetting('software_updates_automatic', e.target.checked)}
                                aria-label="Install updates automatically"
                            />
                        </label>

                        <label className={styles.settingRow} data-testid="update-notice-toggle">
                            <div className={styles.settingIcon}>
                                <SparkleIcon />
                            </div>
                            <div className={styles.settingInfo}>
                                <span className={styles.settingTitle}>Tell me when an update is ready</span>
                                <span className={styles.settingDesc}>
                                    Turning this off does not stop updates. They keep arriving, and this page is where you will see them.
                                </span>
                            </div>
                            <ToggleSwitch
                                checked={settings.software_updates_notify !== false}
                                onChange={(e) => updateSetting('software_updates_notify', e.target.checked)}
                                aria-label="Tell me when an update is ready"
                            />
                        </label>
                    </div>
                </>
            )}

            {/* Experimental */}
            <div className={styles.sectionLabel}>Experimental</div>
            <div className={styles.settingsGroup} data-testid="experimental-settings-group">
                <label className={styles.settingRow} data-testid="custom-apps-toggle">
                    <div className={styles.settingIcon}>
                        <PackageIcon />
                    </div>
                    <div className={styles.settingInfo}>
                        <span className={styles.settingTitle}>Apps</span>
                        <span className={styles.settingDesc}>
                            Apps let your Omnideck agents build and run personalized tools for you. Only use Apps you trust.
                        </span>
                    </div>
                    <ToggleSwitch
                        checked={!!settings.custom_apps_enabled}
                        onChange={(e) => updateSetting('custom_apps_enabled', e.target.checked)}
                        aria-label="Apps"
                    />
                </label>

                <label className={styles.settingRow} data-testid="custom-tools-toggle">
                    <div className={styles.settingIcon}>
                        <WrenchIcon size={16} />
                    </div>
                    <div className={styles.settingInfo}>
                        <span className={styles.settingTitle}>Custom Tools</span>
                        <span className={styles.settingDesc}>
                            The agent can create, save, and run reusable tools.
                        </span>
                    </div>
                    <ToggleSwitch
                        checked={!!settings.custom_tools_enabled}
                        onChange={(e) => updateSetting('custom_tools_enabled', e.target.checked)}
                        aria-label="Custom Tools"
                    />
                </label>

                <div className={styles.groupFootnote}>
                    Experimental features are early access and may change, break, or be removed without notice. Backward compatibility is not guaranteed.
                </div>
            </div>

            {/* Default Agent */}
            <div className={styles.sectionLabel}>Default Agent</div>

            <div className={`${styles.settingRow} ${styles.defaultAgentRow}`}>
                <div className={styles.settingIcon}>
                    <PackageIcon />
                </div>
                <div className={styles.settingInfo}>
                    <span className={styles.settingTitle}>Default Agent</span>
                    <span className={styles.settingDesc}>The agent profile used as the system agent.</span>
                </div>
                <select
                    className={styles.select}
                    value={settings.default_agent || 'omnideck'}
                    onChange={(e) => updateSetting('default_agent', e.target.value)}
                >
                    {profiles.map((p) => (
                        <option key={p.id} value={p.id}>{p.name}</option>
                    ))}
                </select>
            </div>

            {/* Model defaults */}
            <div className={styles.sectionLabel}>Model Defaults</div>

            <div className={styles.modelDefaults} data-testid="model-defaults-group">
                <section className={styles.modelSetting} data-testid="vision-model-setting">
                    <div className={styles.modelHeader}>
                        <div className={styles.settingIcon}>
                            <EyeIcon size={16} />
                        </div>
                        <div className={styles.settingInfo}>
                            <span className={styles.settingTitle}>Vision</span>
                            <span className={styles.settingDesc}>Image descriptions and screenshot analysis.</span>
                        </div>
                    </div>
                    <div className={styles.modelBody}>
                        <div className={styles.pickerRow} data-testid="vision-model-picker">
                            <ModelPicker
                                providers={providers}
                                selectedProvider={settings.vision_provider || null}
                                selectedModel={settings.vision_model || null}
                                onSelect={(p, m) => updateProviderModel('vision_provider', 'vision_model', p, m)}
                                placeholder="Choose a vision model…"
                                capability="vision"
                                inline
                            />
                        </div>
                        <span className={styles.modelRecommendation}>Tested with Qwen3.5.</span>

                        <button
                            type="button"
                            className={`${styles.groupDisclosure} ${visionAdvancedOpen ? styles.groupDisclosureOpen : ''}`}
                            onClick={() => setVisionAdvancedOpen((v) => !v)}
                            aria-expanded={visionAdvancedOpen}
                            data-testid="vision-advanced-toggle"
                        >
                            <ChevronRightIcon className={styles.chev} />
                            Advanced inference
                        </button>

                        {visionAdvancedOpen && (
                            <div className={styles.groupBody} data-testid="vision-advanced-panel">
                                <label className={styles.groupRow} data-testid="vision-think-toggle">
                                    <div className={styles.settingInfo}>
                                        <span className={styles.settingTitle}>Thinking</span>
                                        <span className={styles.settingDesc}>Step-by-step reasoning before answering. Slower but more accurate.</span>
                                    </div>
                                    <ToggleSwitch
                                        checked={!!settings.vision_think}
                                        onChange={(e) => updateSetting('vision_think', e.target.checked)}
                                        aria-label="Thinking"
                                    />
                                </label>
                                {[
                                    { key: 'temperature', label: 'Temperature', desc: '0.0 = deterministic, 0.7 = general, 1.0+ = creative.', step: 0.1 },
                                    { key: 'top_k', label: 'Top K', desc: '10 = factual, 40 = general, 100+ = creative.', providers: ['ollama', 'anthropic'] },
                                    { key: 'top_p', label: 'Top P', desc: '0.5 = focused, 0.9 = general, 1.0 = everything.', step: 0.05 },
                                    { key: 'num_ctx', label: 'Context Window', desc: 'Maximum context window in tokens.', providers: ['ollama'] },
                                    { key: 'num_predict', label: 'Max Output (num_predict)', desc: 'Tokens the model can generate per call.' },
                                ].filter(({ providers }) => !providers || providers.includes(visionProvider)).map(({ key, label, desc, step }) => (
                                    <div key={key} className={styles.groupRow}>
                                        <div className={styles.settingInfo}>
                                            <span className={styles.settingTitle}>{label}</span>
                                            <span className={styles.settingDesc}>{desc}</span>
                                        </div>
                                        <input
                                            className={styles.numberInput}
                                            type="number"
                                            step={step ?? 1}
                                            value={settings.vision_options?.[key] ?? ''}
                                            data-testid={`vision-option-${key}`}
                                            onChange={(e) => {
                                                const raw = e.target.value;
                                                const num = raw === '' ? null : Number(raw);
                                                updateSetting('vision_options', {
                                                    ...(settings.vision_options || {}),
                                                    [key]: num,
                                                });
                                            }}
                                        />
                                    </div>
                                ))}
                            </div>
                        )}
                    </div>
                </section>

                <section className={styles.modelSetting} data-testid="compaction-model-setting">
                    <div className={styles.modelHeader}>
                        <div className={styles.settingIcon}>
                            <CompactionIcon />
                        </div>
                        <div className={styles.settingInfo}>
                            <span className={styles.settingTitle}>Compaction</span>
                            <span className={styles.settingDesc}>Summarizes conversation history when context fills up.</span>
                        </div>
                    </div>
                    <div className={styles.modelBody}>
                        <div className={styles.pickerRow} data-testid="compaction-model-picker">
                            <ModelPicker
                                providers={providers}
                                selectedProvider={settings.compaction_provider || null}
                                selectedModel={settings.compaction_model || null}
                                onSelect={(p, m) => updateProviderModel('compaction_provider', 'compaction_model', p, m)}
                                placeholder="Choose a compaction model…"
                                inline
                            />
                        </div>
                        <span className={styles.modelRecommendation}>Recommended: kimi-k2.5.</span>
                    </div>
                </section>

                <section className={styles.modelSetting} data-testid="title-model-setting">
                    <div className={styles.modelHeader}>
                        <div className={styles.settingIcon}>
                            <PackageIcon />
                        </div>
                        <div className={styles.settingInfo}>
                            <span className={styles.settingTitle}>Title generation</span>
                            <span className={styles.settingDesc}>Creates a 3–5 word title for each new conversation.</span>
                        </div>
                    </div>
                    <div className={styles.modelBody}>
                        <div className={styles.pickerRow} data-testid="title-model-picker">
                            <ModelPicker
                                providers={providers}
                                selectedProvider={settings.title_provider || null}
                                selectedModel={settings.title_model || null}
                                onSelect={(p, m) => updateProviderModel('title_provider', 'title_model', p, m)}
                                placeholder="Choose a title model…"
                                inline
                            />
                        </div>
                    </div>
                </section>
            </div>
        </div>
    );
}
