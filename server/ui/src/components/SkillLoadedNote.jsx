import styles from './SkillLoadedNote.module.css';

const STATUS_LABEL = {
    loaded: null,
    already_loaded: 'already loaded',
    unavailable: 'unavailable',
};

/**
 * Inline note under a user message listing the skills its `/` shortcuts
 * loaded, so a load that didn't happen is visible rather than silent.
 *
 * `skills`: [{ id, skillName, status }] — consecutive skill_loaded items.
 */
export default function SkillLoadedNote({ skills }) {
    const failed = skills.some((skill) => skill.status === 'unavailable');
    return (
        <div className={`${styles.note} ${failed ? styles.failed : ''}`} data-testid="skill-loaded-note">
            <i className={`bi ${failed ? 'bi-exclamation-triangle' : 'bi-lightning-charge'}`} aria-hidden="true" />
            <span className={styles.label}>{skills.length === 1 ? 'Skill' : 'Skills'}</span>
            {skills.map((skill) => (
                <span
                    key={skill.id}
                    className={`${styles.skill} ${skill.status === 'unavailable' ? styles.unavailable : ''}`}
                >
                    {skill.skillName}
                    {STATUS_LABEL[skill.status] && (
                        <span className={styles.status}> ({STATUS_LABEL[skill.status]})</span>
                    )}
                </span>
            ))}
        </div>
    );
}
