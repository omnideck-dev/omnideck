import { useEffect, useMemo, useRef, useState } from 'react';

import { useAppData } from '../../contexts/AppData.jsx';
import useToolCategories from '../../hooks/useToolCategories.js';
import { downloadSkillPack, importPackFile, importSummaryText } from '../../utils/packs.js';
import { useToast } from '../ToastProvider.jsx';
import Button from '../primitives/Button.jsx';
import LibraryHeader from '../primitives/LibraryHeader.jsx';
import SkillBuilder from './SkillBuilder.jsx';
import SkillList from './SkillList.jsx';
import styles from './SkillsTab.module.css';

/**
 * Settings → Skills: library and editor with inline tool disclosures.
 */
export default function SkillsTab({ initialSkillId, onOpenIntegration, selectionRequest }) {
    const { skillsHook } = useAppData();
    const { skills, addSkills, createSkill, updateSkill, deleteSkill } = skillsHook;
    const { addToast } = useToast();
    const categories = useToolCategories();
    const [search, setSearch] = useState('');
    const [selectedId, setSelectedId] = useState(initialSkillId || null);
    useEffect(() => { if (initialSkillId) { setDraft(null); setSelectedId(initialSkillId); } }, [initialSkillId, selectionRequest]);
    const [draft, setDraft] = useState(null);
    const importInputRef = useRef(null);

    // Import a pack picked from disk. The response carries the freshly created
    // records, so merge them into the list instead of refetching. Reset the
    // input so re-picking the same file re-fires the change event.
    const handleImportFile = async (e) => {
        const file = e.target.files?.[0];
        e.target.value = '';
        if (!file) return;
        const result = await importPackFile(file);
        if (!result.ok) {
            addToast(result.error, { type: 'error', title: 'Import failed' });
            return;
        }
        addSkills(result.data.skills || []);
        addToast(importSummaryText(result.data), { type: 'success' });
    };

    const selectedSkill = draft ?? skills.find((s) => s.id === selectedId) ?? null;

    const q = search.trim().toLowerCase();
    const filteredSkills = useMemo(() => (
        q ? skills.filter((s) => s.name.toLowerCase().includes(q) || (s.description || '').toLowerCase().includes(q)) : skills
    ), [skills, q]);
    const views = [{ id: 'skills', label: 'My Skills', count: skills.length }];

    const handleNew = () => {
        setSelectedId(null);
        setDraft({ id: `new_${Date.now()}`, name: 'New Skill', description: '', prompt: '', tool_categories: [], _unsaved: true });
    };

    return (
        <div className={styles.tab} data-testid="skills-tab">
            <LibraryHeader
                views={views}
                activeView="skills"
                onViewChange={() => {}}
                searchValue={search}
                onSearchChange={setSearch}
                searchPlaceholder="Search skills…"
                actions={(
                    <>
                        <input
                            ref={importInputRef}
                            type="file"
                            accept=".omnideck.json,application/json"
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
                )}
            />
            {(
                <div className={styles.master}>
                    <SkillList
                        skills={filteredSkills}
                        categories={categories}
                        selectedId={draft ? null : selectedId}
                        onSelect={(id) => { setDraft(null); setSelectedId(id); }}
                        onNew={handleNew}
                        onExport={(id) => downloadSkillPack(id)}
                    />
                    <SkillBuilder
                        skill={selectedSkill}
                        categories={categories}
                        onOpenIntegration={onOpenIntegration}
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
                        onExport={(id) => downloadSkillPack(id)}
                    />
                </div>
            )}
        </div>
    );
}
