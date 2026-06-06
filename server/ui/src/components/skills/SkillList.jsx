import styles from './SkillList.module.css';

function metaText(skill, categories) {
    const granted = skill.tool_categories || [];
    const byId = new Map(categories.map((c) => [c.id, c]));
    const toolCount = granted.reduce((n, id) => n + (byId.get(id)?.tool_count || 0), 0);
    const catWord = granted.length === 1 ? 'category' : 'categories';
    const toolWord = toolCount === 1 ? 'tool' : 'tools';
    return `${granted.length} ${catWord} · ${toolCount} ${toolWord}`;
}

function SkillItem({ skill, categories, selected, onSelect }) {
    return (
        <li
            className={`${styles.item} ${selected ? styles.itemActive : ''}`}
            onClick={() => onSelect(skill.id)}
            role="button"
            tabIndex={0}
            data-testid={`skill-item-${skill.id}`}
            onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onSelect(skill.id); } }}
        >
            <div className={styles.itemBody}>
                <span className={styles.name}>{skill.name}</span>
                {skill.description && <span className={styles.desc}>{skill.description}</span>}
                <div className={styles.metaRow}>
                    <span className={styles.metaText}>{metaText(skill, categories)}</span>
                </div>
            </div>
        </li>
    );
}

export default function SkillList({ skills, categories, selectedId, onSelect, onNew }) {
    return (
        <div className={styles.panel}>
            <div className={styles.header}>
                <span className={styles.headerLabel}>Skills</span>
                <button className={styles.newBtn} onClick={onNew}>+ New</button>
            </div>
            <div className={styles.list}>
                {skills.map((skill) => (
                    <SkillItem
                        key={skill.id}
                        skill={skill}
                        categories={categories}
                        selected={selectedId === skill.id}
                        onSelect={onSelect}
                    />
                ))}
            </div>
        </div>
    );
}
