import styles from './inference.module.css';
import InferencePresets from './InferencePresets.jsx';
import InferenceAdvanced from './InferenceAdvanced.jsx';

export default function InferenceSettings({ draft, capabilities, activePreset, onFieldChange, onApplyPreset }) {
    return (
        <>
            <section className={styles.section}>
                <div className={styles.sectionLabel}>Inference Preset</div>
                <InferencePresets
                    capabilities={capabilities}
                    activePreset={activePreset}
                    onApply={onApplyPreset}
                />
            </section>
            <section className={styles.section}>
                <InferenceAdvanced
                    draft={draft}
                    capabilities={capabilities}
                    onChange={onFieldChange}
                />
            </section>
        </>
    );
}
