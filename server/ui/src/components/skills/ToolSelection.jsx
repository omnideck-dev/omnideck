import { useEffect, useRef, useState } from 'react';

import Button from '../primitives/Button.jsx';
import ExpandableSelectionRow from '../ExpandableSelectionRow.jsx';
import Popover from '../primitives/Popover.jsx';
import SearchInput from '../primitives/SearchInput.jsx';
import SelectionToolList from './SelectionToolList.jsx';
import { categoryIcon } from './skillCategoryIcons.js';
import styles from './ToolSelection.module.css';

/** One selection list. Skills contribute their saved groups, never a copied grant. */
export default function ToolSelection({
    skills = [], categories = [], skillIds = [], categoryIds = [],
    onSkillsChange, onCategoriesChange, onOpenIntegration, onOpenSkill,
}) {
    const [adding, setAdding] = useState(false);
    const [query, setQuery] = useState('');
    const trigger = useRef(null);
    const search = useRef(null);
    const focusAfterRemoval = useRef(false);
    useEffect(() => {
        if (adding) search.current?.querySelector('input')?.focus();
    }, [adding]);
    const byId = new Map(categories.map(c => [c.id, c]));
    const getCategory = id => byId.get(id) || {
        id, label: id.startsWith('integration:') ? 'Integration' : id,
        description: '',
        connected: false, tools: [], missing: true,
    };
    const rows = skillIds.map(id => {
        const skill = skills.find(s => s.id === id);
        return { key: `skill:${id}`, id, skill: true, label: skill?.name || id,
            description: skill?.description || '', groups: (skill?.tool_categories || []).map(getCategory),
            missing: !skill };
    }).concat(categoryIds.map(id => ({ ...getCategory(id), key: `tool:${id}` })));
    const availableGroups = [
        ...(onSkillsChange ? [{ label: 'Skills', options: skills.filter(s => !skillIds.includes(s.id)).map(s => ({ ...s, label: s.name, skill: true })) }] : []),
        { label: 'Built-in tools', options: categories.filter(c => !c.connection_id && !categoryIds.includes(c.id)) },
        { label: 'Integrations', options: categories.filter(c => c.connection_id && !categoryIds.includes(c.id)) },
    ];
    const canAdd = availableGroups.some(g => g.options.length);
    useEffect(() => {
        if (focusAfterRemoval.current && canAdd) {
            trigger.current?.focus();
            focusAfterRemoval.current = false;
        }
    }, [canAdd, skillIds, categoryIds]);
    const groups = availableGroups.map(g => ({ ...g, options: g.options.filter(c => `${c.label} ${c.description || ''}`.toLowerCase().includes(query.trim().toLowerCase())) }));
    const icon = row => row.skill ? 'bi-stars' : row.connection_id || row.id.startsWith('integration:') ? 'bi-plug' : categoryIcon(row.id);
    const close = () => { setAdding(false); trigger.current?.focus(); };
    const add = row => {
        if (row.skill) onSkillsChange([...skillIds, row.id]);
        else onCategoriesChange([...categoryIds, row.id]);
        close();
    };
    const remove = row => {
        focusAfterRemoval.current = true;
        if (row.skill) onSkillsChange(skillIds.filter(id => id !== row.id));
        else onCategoriesChange(categoryIds.filter(id => id !== row.id));
    };
    const toolDetails = category => (
        <>
            <SelectionToolList category={category} />
            {onOpenIntegration && (category.connection_id || category.id.startsWith('integration:')) && (
                <div className={styles.action}><Button variant="outline" onClick={() => onOpenIntegration(category.connection_id || category.id.slice(12))}>
                    Manage in Integrations <i className="bi bi-arrow-up-right" aria-hidden="true" />
                </Button></div>
            )}
        </>
    );
    return (
        <div>
            <ul className={styles.list}>
                {rows.map(row => (
                    <ExpandableSelectionRow key={row.key} testId={`selected-${row.key}`}
                        icon={<i className={`bi ${icon(row)}`} />} name={row.label}
                        description={row.connection_id ? `${row.operations?.length || 0} tools selected in Integrations` : row.description}
                        meta={row.skill && row.groups.length ? `Uses ${row.groups.map(c => c.label).join(', ')}`
                            : !row.skill && !row.connection_id && !row.missing ? `${row.tools?.length || 0} tools` : undefined}
                        onRemove={() => remove(row)}>
                        {row.skill ? <>
                            {row.groups.length ? row.groups.map(c => (
                                <section key={c.id} className={styles.group} aria-label={c.label}>
                                    <h3>{c.label}</h3>{toolDetails(c)}
                                </section>
                            )) : !row.missing && <p>This skill doesn’t need any tools.</p>}
                            {!row.missing && onOpenSkill && <div className={styles.action}><Button variant="outline" onClick={() => onOpenSkill(row.id)}>Edit skill</Button></div>}
                        </> : toolDetails(row)}
                    </ExpandableSelectionRow>
                ))}
            </ul>
            {!rows.length && <p className={styles.empty}>Nothing added yet.</p>}
            <div className={styles.add}><span ref={node => { trigger.current = node?.querySelector('button'); }}><Button variant="outline" aria-haspopup="dialog" aria-expanded={adding}
                disabled={!canAdd} title={!canAdd ? 'All available items are already added' : undefined}
                onClick={() => { setQuery(''); setAdding(!adding); }}><i className="bi bi-plus-lg" aria-hidden="true" /> Add</Button></span></div>
            {adding && canAdd && <Popover anchorRef={trigger} onClose={close} width={420} maxHeight={380} role="dialog" ariaLabel="Add skills and tools" className={styles.picker}>
                <div ref={search} className={styles.search}><SearchInput value={query} onChange={setQuery} ariaLabel="Search skills and tools" placeholder="Search…" /></div>
                <div className={styles.options}>
                    {groups.filter(g => g.options.length).map(g => <section key={g.label} aria-label={g.label}>
                        <h3>{g.label}</h3>{g.options.map(c => <button key={c.id} type="button" className={styles.option} onClick={() => add(c)}>
                            <i className={`bi ${icon(c)}`} aria-hidden="true" /><span className={styles.info}><span className={styles.name}>{c.label}</span><span className={styles.description}>{c.description}</span></span><i className="bi bi-plus" aria-hidden="true" />
                        </button>)}
                    </section>)}
                    {!groups.some(g => g.options.length) && <p className={styles.empty}>Nothing matches your search.</p>}
                </div>
            </Popover>}
        </div>
    );
}
