import styles from './SkillLoadedNote.module.css';

const STATUS_LABEL = {
    loaded: null,
    already_loaded: 'already loaded',
    unavailable: 'unavailable',
};

/** The skill's current name, if it differs from the name it was used under. */
function _renamedTo(skill, currentNames) {
    const current = currentNames?.get(skill.skillId);
    return current && current !== skill.skillName ? current : null;
}

/**
 * Inline note under a user message listing the skills its `/` shortcuts
 * loaded, so a load that didn't happen is visible rather than silent.
 *
 * Each skill keeps the name it had when it was used. If it has since been
 * renamed, the current name follows, so the two are recognizably the same.
 *
 * `skills`: [{ id, skillId, skillName, status }] — consecutive skill_loaded items.
 * `currentNames`: Map of skill id to its current name, when known.
 */
export default function SkillLoadedNote({ skills, currentNames }) {
    const failed = skills.some((skill) => skill.status === 'unavailable');
    return (
        <div className={`${styles.note} ${failed ? styles.failed : ''}`} data-testid="skill-loaded-note">
            <i className={`bi ${failed ? 'bi-exclamation-triangle' : 'bi-lightning-charge'}`} aria-hidden="true" />
            <span className={styles.label}>{skills.length === 1 ? 'Skill' : 'Skills'}</span>
            {skills.map((skill) => {
                const renamedTo = _renamedTo(skill, currentNames);
                return (
                    <span
                        key={skill.id}
                        className={`${styles.skill} ${skill.status === 'unavailable' ? styles.unavailable : ''}`}
                    >
                        {skill.skillName}
                        {STATUS_LABEL[skill.status] && (
                            <span className={styles.status}> ({STATUS_LABEL[skill.status]})</span>
                        )}
                        {renamedTo && (
                            <span className={styles.status}>
                                {' · now '}
                                <em className={styles.currentName}>{renamedTo}</em>
                            </span>
                        )}
                    </span>
                );
            })}
        </div>
    );
}
