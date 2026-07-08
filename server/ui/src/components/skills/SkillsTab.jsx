import { useEffect, useMemo, useRef, useState } from 'react';

import useSkills from '../../hooks/useSkills.js';
import { downloadSkillBundle, importBundleFile, importSummaryText } from '../../utils/bundles.js';
import { useToast } from '../ToastProvider.jsx';
import Button from '../primitives/Button.jsx';
import CategoryCatalog from './CategoryCatalog.jsx';
import LibraryHeader from '../primitives/LibraryHeader.jsx';
import SkillBuilder from './SkillBuilder.jsx';
import SkillList from './SkillList.jsx';
import styles from './SkillsTab.module.css';

/**
 * Settings → Skills. A SIGNAL Library Header switches between My Skills (a
 * master-detail list + editor over /api/skills) and Tool Categories (a
 * read-only catalog from /api/tool-categories). Search re-scopes to the
 * active view.
 */
export default function SkillsTab() {
    const { skills, refresh, createSkill, updateSkill, deleteSkill } = useSkills();
    const { addToast } = useToast();
    const [categories, setCategories] = useState([]);
    const [view, setView] = useState('skills');
    const [search, setSearch] = useState('');
    const [selectedId, setSelectedId] = useState(null);
    const [draft, setDraft] = useState(null);
    const importInputRef = useRef(null);

    useEffect(() => {
        fetch('/api/tool-categories')
            .then((r) => r.json())
            .then((data) => setCategories(Array.isArray(data) ? data : []))
            .catch(() => {});
    }, []);

    // Import a bundle picked from disk, then refresh the skill list. Reset the
    // input so re-picking the same file re-fires the change event.
    const handleImportFile = async (e) => {
        const file = e.target.files?.[0];
        e.target.value = '';
        if (!file) return;
        const result = await importBundleFile(file);
        if (!result.ok) {
            addToast(result.error, { type: 'error', title: 'Import failed' });
            return;
        }
        await refresh();
        addToast(importSummaryText(result.data), { type: 'success' });
    };

    const selectedSkill = draft ?? skills.find((s) => s.id === selectedId) ?? null;

    const q = search.trim().toLowerCase();
    const filteredSkills = useMemo(() => (
        q ? skills.filter((s) => s.name.toLowerCase().includes(q) || (s.description || '').toLowerCase().includes(q)) : skills
    ), [skills, q]);
    const filteredCategories = useMemo(() => (
        q ? categories.filter((c) => c.label.toLowerCase().includes(q) || (c.description || '').toLowerCase().includes(q)) : categories
    ), [categories, q]);

    const views = [
        { id: 'skills', label: 'My Skills', count: skills.length },
        { id: 'categories', label: 'Tool Categories', count: categories.length },
    ];

    const handleNew = () => {
        setSelectedId(null);
        setDraft({ id: `new_${Date.now()}`, name: 'New Skill', description: '', prompt: '', tool_categories: [], _unsaved: true });
    };

    return (
        <div className={styles.tab} data-testid="skills-tab">
            <LibraryHeader
                views={views}
                activeView={view}
                onViewChange={setView}
                searchValue={search}
                onSearchChange={setSearch}
                searchPlaceholder={view === 'skills' ? 'Search skills…' : 'Search tool categories…'}
                actions={view === 'skills' ? (
                    <>
                        <input
                            ref={importInputRef}
                            type="file"
                            accept=".json,application/json"
                            style={{ display: 'none' }}
                            onChange={handleImportFile}
                            data-testid="skills-import-input"
                        />
                        <Button
                            variant="outline"
                            onClick={() => importInputRef.current?.click()}
                            data-testid="skills-import"
                        >
                            <i className="bi bi-upload" /> Import
                        </Button>
                    </>
                ) : null}
            />
            {view === 'skills' ? (
                <div className={styles.master}>
                    <SkillList
                        skills={filteredSkills}
                        categories={categories}
                        selectedId={draft ? null : selectedId}
                        onSelect={(id) => { setDraft(null); setSelectedId(id); }}
                        onNew={handleNew}
                        onExport={(id) => downloadSkillBundle(id)}
                    />
                    <SkillBuilder
                        skill={selectedSkill}
                        categories={categories}
                        onSave={async (updated) => {
                            if (updated._unsaved) {
                                const { _unsaved, id, ...payload } = updated;
                                const res = await createSkill(payload);
                                if (res.ok) { setDraft(null); setSelectedId(res.data.id); }
                                return res;
                            }
                            return updateSkill(updated.id, updated);
                        }}
                        onDelete={async (id) => {
                            if (draft && draft.id === id) { setDraft(null); return; }
                            await deleteSkill(id);
                            setSelectedId(null);
                        }}
                    />
                </div>
            ) : (
                <CategoryCatalog categories={filteredCategories} />
            )}
        </div>
    );
}
