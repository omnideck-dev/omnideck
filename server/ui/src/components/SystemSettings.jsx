import { useState, useEffect, useCallback, useMemo } from 'react';
import { useAppData } from '../contexts/AppData.jsx';
import styles from './SystemSettings.module.css';
import ModelPicker from './ModelPicker.jsx';
import PackageIcon from './icons/PackageIcon';
import EyeIcon from './icons/EyeIcon';
import CompactionIcon from './icons/CompactionIcon';
import ToggleSwitch from './ToggleSwitch.jsx';
import WrenchIcon from './icons/WrenchIcon.jsx';
import DownloadIcon from './icons/DownloadIcon';
import SparkleIcon from './icons/SparkleIcon';
import SoftwareUpdateStatus from './SoftwareUpdateStatus.jsx';
import Select from './primitives/Select.jsx';
import { useIsHosted } from '../features/app/OmnideckHost.jsx';
import SpecializedModelOptions, { ModelDefaultsSummary } from './SpecializedModelOptions.jsx';
import { resolveInferenceCapabilities, sanitizeInferenceOptions } from './inference';

export default function SystemSettings() {
    const { providersHook, refreshFeatures } = useAppData();
    const { providers } = providersHook;
    const [profiles, setProfiles] = useState([]);
    const [settings, setSettings] = useState({ default_agent: 'omnideck' });
    const [loading, setLoading] = useState(true);
    const [visionAdvancedOpen, setVisionAdvancedOpen] = useState(false);
    const [compactionAdvancedOpen, setCompactionAdvancedOpen] = useState(false);
    const [resolvedModels, setResolvedModels] = useState({});
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

    const updateSettings = useCallback(async (patch) => {
        const previousValues = Object.fromEntries(Object.keys(patch).map((key) => [key, settings[key]]));
        setSettings((prev) => ({ ...prev, ...patch }));
        try {
            const res = await fetch('/api/settings', {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(patch),
            });
            if (res.ok) {
                const updated = await res.json();
                setSettings(updated);
                if ('custom_apps_enabled' in patch || 'custom_tools_enabled' in patch) {
                    await refreshFeatures();
                }
                return;
            }
        } catch {
            // Restore the server-backed value below.
        }
        setSettings((prev) => ({ ...prev, ...previousValues }));
    }, [refreshFeatures, settings]);

    const updateSetting = useCallback((key, value) => updateSettings({ [key]: value }), [updateSettings]);

    // Update a (provider, model) pair atomically so they always stay in sync.
    const updateProviderModel = useCallback((role, provider, model, info) => {
        const capabilities = resolveInferenceCapabilities(provider, info);
        const patch = {
            [`${role}_provider`]: provider || '',
            [`${role}_model`]: model || '',
        };
        if (role === 'vision') {
            patch.vision_options = sanitizeInferenceOptions(
                settings.vision_options,
                capabilities,
                { allowContext: capabilities.api === 'ollama' },
            );
            if (capabilities.thinkingRequired) patch.vision_think = true;
            else if (!capabilities.controls.includes('think')) patch.vision_think = false;
        } else if (role === 'compaction') {
            patch.compaction_options = sanitizeInferenceOptions(
                settings.compaction_options,
                capabilities,
                { allowContext: capabilities.api === 'ollama' },
            );
        }
        setResolvedModels((prev) => ({ ...prev, [role]: { provider, model, info } }));
        updateSettings(patch);
    }, [settings.compaction_options, settings.vision_options, updateSettings]);

    const handleModelResolved = useCallback((role, provider, model, info) => {
        setResolvedModels((prev) => ({ ...prev, [role]: { provider, model, info } }));
    }, []);
    const handleVisionResolved = useCallback(
        (provider, model, info) => handleModelResolved('vision', provider, model, info),
        [handleModelResolved],
    );
    const handleCompactionResolved = useCallback(
        (provider, model, info) => handleModelResolved('compaction', provider, model, info),
        [handleModelResolved],
    );
    const handleTitleResolved = useCallback(
        (provider, model, info) => handleModelResolved('title', provider, model, info),
        [handleModelResolved],
    );

    const roleCapabilities = useMemo(() => Object.fromEntries(
        ['vision', 'compaction', 'title'].map((role) => {
            const provider = settings[`${role}_provider`] || providers[0]?.name || 'ollama';
            const resolved = resolvedModels[role];
            const info = resolved?.provider === provider && resolved?.model === settings[`${role}_model`]
                ? resolved.info
                : null;
            return [role, resolveInferenceCapabilities(provider, info)];
        }),
    ), [providers, resolvedModels, settings]);

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
                <Select
                    className={styles.select}
                    value={settings.default_agent || 'omnideck'}
                    onChange={(value) => updateSetting('default_agent', value)}
                    ariaLabel="Default agent"
                    testId="default-agent-select"
                    options={profiles.map((profile) => ({
                        value: profile.id,
                        label: profile.name,
                    }))}
                />
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
                                onSelect={(p, m, info) => updateProviderModel('vision', p, m, info)}
                                onModelResolved={handleVisionResolved}
                                placeholder="Choose a vision model…"
                                capability="vision"
                                inline
                            />
                        </div>
                        <SpecializedModelOptions
                            role="vision"
                            capabilities={roleCapabilities.vision}
                            options={settings.vision_options}
                            think={!!settings.vision_think}
                            open={visionAdvancedOpen}
                            onToggle={() => setVisionAdvancedOpen((value) => !value)}
                            onPatch={updateSettings}
                        />
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
                                onSelect={(p, m, info) => updateProviderModel('compaction', p, m, info)}
                                onModelResolved={handleCompactionResolved}
                                placeholder="Choose a compaction model…"
                                inline
                            />
                        </div>
                        <SpecializedModelOptions
                            role="compaction"
                            capabilities={roleCapabilities.compaction}
                            options={settings.compaction_options}
                            open={compactionAdvancedOpen}
                            onToggle={() => setCompactionAdvancedOpen((value) => !value)}
                            onPatch={updateSettings}
                        />
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
                                onSelect={(p, m, info) => updateProviderModel('title', p, m, info)}
                                onModelResolved={handleTitleResolved}
                                placeholder="Choose a title model…"
                                inline
                            />
                        </div>
                        <ModelDefaultsSummary capabilities={roleCapabilities.title} role="title" />
                    </div>
                </section>
            </div>
        </div>
    );
}
