import { useEffect, useMemo, useRef, useState } from 'react';

import { useAppData } from '../../contexts/AppData.jsx';
import useSkills from '../../hooks/useSkills.js';
import { importPackFile, importSummaryText } from '../../utils/packs.js';
import Badge from '../Badge.jsx';
import ProfileBuilder from '../ProfileBuilder.jsx';
import { useToast } from '../ToastProvider.jsx';
import Button from '../primitives/Button.jsx';
import IconButton from '../primitives/IconButton.jsx';
import Modal from '../primitives/Modal.jsx';
import RowDeleteButton from '../primitives/RowDeleteButton.jsx';
import SearchInput from '../primitives/SearchInput.jsx';
import SortableTable from '../primitives/SortableTable.jsx';
import ExportProfileModal from './ExportProfileModal.jsx';
import styles from './AgentsView.module.css';

// Sortable columns, also shown in the toolbar's sort select.
const SORTS = {
    name: { label: 'Name', defaultDir: 'asc', value: (p) => (p.name || '').toLowerCase() },
    model: { label: 'Model', defaultDir: 'asc', value: (p) => (p.model || '').toLowerCase() },
    status: { label: 'Status', defaultDir: 'asc', value: (p) => (p.enabled === false ? 1 : 0) },
};

function draftAgent(providers) {
    return {
        id: `custom_${Date.now()}`,
        name: 'New Agent',
        description: '',
        icon: '🤖',
        provider: providers[0]?.name || '',
        model: '',
        system_prompt: '',
        skills: [],
        allow_spawn: true,
        allow_load_skills: true,
        _unsaved: true,
    };
}

/**
 * Agents view: a searchable, sortable table of agent profiles that owns the
 * full width until an agent is selected, then the agent opens full-width with a
 * back nav. Self-contained; it drives profile state
 * through the shared profilesHook so chat and this view stay in sync. The
 * detail is the existing ProfileBuilder editor.
 */
export default function AgentsView() {
    const { profilesHook } = useAppData();
    const { skills, addSkills } = useSkills();
    const { addToast } = useToast();
    const [providers, setProviders] = useState([]);
    const [categories, setCategories] = useState([]);
    const [draft, setDraft] = useState(null);
    const [openId, setOpenId] = useState(null);
    const [deleteConflict, setDeleteConflict] = useState(null);
    const [query, setQuery] = useState('');
    const [sort, setSort] = useState({ key: 'name', dir: 'asc' });
    // Profile pending export (its options modal is open) and the hidden file
    // input backing the Import button.
    const [exportProfile, setExportProfile] = useState(null);
    const importInputRef = useRef(null);
    // Unsaved-changes guard: the editor reports its dirty state up, and the
    // back nav shows an inline warning instead of discarding silently.
    const [builderDirty, setBuilderDirty] = useState(false);
    const [showUnsaved, setShowUnsaved] = useState(false);

    useEffect(() => {
        fetch('/api/providers').then((r) => r.json()).then((data) => {
            setProviders(data.providers || []);
        }).catch(() => { });
    }, []);

    // Tool-category metadata for the skill picker (tool counts, connection dots).
    useEffect(() => {
        fetch('/api/tool-categories').then((r) => r.json()).then((data) => {
            setCategories(Array.isArray(data) ? data : []);
        }).catch(() => { });
    }, []);

    // Drop any stale delete conflict when the open agent changes.
    useEffect(() => {
        setDeleteConflict(null);
    }, [openId, draft]);

    const profiles = profilesHook.profiles;
    const selected = draft ?? profiles.find((p) => p.id === openId) ?? null;

    const backToList = () => {
        setDraft(null);
        setOpenId(null);
        setDeleteConflict(null);
        setBuilderDirty(false);
        setShowUnsaved(false);
    };

    // Back nav: warn first if the editor has unsaved edits, otherwise leave.
    const requestBack = () => {
        if (builderDirty) setShowUnsaved(true);
        else backToList();
    };

    const openAgent = (id) => {
        setDraft(null);
        setOpenId(id);
        setBuilderDirty(false);
        setShowUnsaved(false);
    };

    const newAgent = () => {
        setDraft(draftAgent(providers));
        setOpenId(null);
        setBuilderDirty(false);
        setShowUnsaved(false);
    };

    const duplicateFromList = async (p) => {
        const created = await profilesHook.duplicateProfile(p.id);
        if (created) addToast(`Duplicated “${p.name}”.`, { type: 'success' });
    };

    // Import a pack picked from disk. The response carries the freshly created
    // records; merge them into both lists instead of refetching. A profile pack
    // may carry skills. Reset the input so re-picking the same file re-fires.
    const handleImportFile = async (e) => {
        const file = e.target.files?.[0];
        e.target.value = '';
        if (!file) return;
        const result = await importPackFile(file);
        if (!result.ok) {
            addToast(result.error, { type: 'error', title: 'Import failed' });
            return;
        }
        profilesHook.addProfiles(result.data.profiles || []);
        addSkills(result.data.skills || []);
        addToast(importSummaryText(result.data), { type: 'success' });
    };

    // Inline delete from the list row — no modal. A profile pinned by one or
    // more routines can't be deleted (409); surface that as a toast rather than
    // silently no-op'ing, since there's no editor open to show the callout.
    const deleteAgent = async (p) => {
        const result = await profilesHook.deleteProfile(p.id);
        if (result?.conflict) {
            const n = new Set((result.usage || []).map((u) => u.routine_id)).size;
            addToast(
                `“${p.name}” is used by ${n} routine${n === 1 ? '' : 's'}. `
                + `Remove it from ${n === 1 ? 'that routine' : 'them'} first, then delete.`,
                { type: 'error', title: 'Can’t delete agent' },
            );
            return;
        }
        if (openId === p.id) setOpenId(null);
    };

    const visible = useMemo(() => {
        const q = query.trim().toLowerCase();
        const matched = q
            ? profiles.filter((p) => (
                `${p.name || ''} ${p.description || ''} ${p.model || ''} ${p.provider || ''}`
                    .toLowerCase().includes(q)
            ))
            : profiles;
        const value = SORTS[sort.key].value;
        const dir = sort.dir === 'asc' ? 1 : -1;
        return [...matched].sort((a, b) => {
            const av = value(a);
            const bv = value(b);
            if (av < bv) return -dir;
            if (av > bv) return dir;
            return (a.name || '').localeCompare(b.name || '');
        });
    }, [profiles, query, sort]);

    function sortBy(key) {
        setSort((s) => (s.key === key
            ? { key, dir: s.dir === 'asc' ? 'desc' : 'asc' }
            : { key, dir: SORTS[key].defaultDir }));
    }

    const columns = [
        {
            key: 'name',
            header: 'Name',
            sortable: true,
            cellClassName: styles.aname,
            render: (p) => (
                <span className={styles.nameCell} data-testid={`profile-item-${p.id}`}>
                    {p.icon && <span className={styles.avatar}>{p.icon}</span>}
                    <span className={styles.nameText}>
                        <span className={styles.nameLine}>{p.name}</span>
                        {p.description && <span className={styles.descLine}>{p.description}</span>}
                    </span>
                </span>
            ),
        },
        {
            key: 'model',
            header: 'Model',
            sortable: true,
            cellClassName: styles.model,
            render: (p) => (p.model
                ? <span title={p.provider ? `${p.provider} · ${p.model}` : p.model}>{p.model}</span>
                : <span className={styles.muted}>—</span>),
        },
        {
            key: 'skills',
            header: 'Skills',
            cellClassName: styles.skills,
            render: (p) => {
                const n = (p.skills || []).length;
                return n ? `${n} skill${n === 1 ? '' : 's'}` : <span className={styles.muted}>—</span>;
            },
        },
        {
            key: 'status',
            header: 'Status',
            sortable: true,
            render: (p) => (p.enabled === false
                ? <Badge variant="neutral">DISABLED</Badge>
                : <Badge variant="success">ACTIVE</Badge>),
        },
        {
            key: 'actions',
            header: '',
            cellClassName: styles.acts,
            revealOnHover: true,
            render: (p) => (
                <span className={styles.actWrap}>
                    <IconButton
                        title="Export agent"
                        aria-label={`Export ${p.name}`}
                        data-testid="agent-export"
                        onClick={(e) => { e.stopPropagation(); setExportProfile(p); }}
                    >
                        <i className="bi bi-download" />
                    </IconButton>
                    <IconButton
                        title="Duplicate agent"
                        aria-label={`Duplicate ${p.name}`}
                        data-testid="agent-duplicate"
                        onClick={(e) => { e.stopPropagation(); duplicateFromList(p); }}
                    >
                        <i className="bi bi-files" />
                    </IconButton>
                    <RowDeleteButton
                        title="Delete agent"
                        data-testid="agent-delete"
                        onConfirm={() => deleteAgent(p)}
                    />
                </span>
            ),
        },
    ];

    // Rendered in whichever branch is active below; defined once so the two
    // mount points can't drift.
    const exportModal = exportProfile && (
        <ExportProfileModal
            profile={exportProfile}
            onClose={() => setExportProfile(null)}
        />
    );

    // Selecting an agent replaces the list with the full editor; a back nav in
    // the header returns to the list. Full-width either way.
    if (selected) {
        return (
            <div className={styles.view} data-testid="agents-view">
                <div className={styles.detailHead}>
                    <Button
                        variant="ghost"
                        onClick={requestBack}
                        data-testid="agent-detail-back"
                    >
                        <i className="bi bi-arrow-left" /> Agents
                    </Button>
                </div>
                {showUnsaved && (
                    <Modal
                        onClose={() => setShowUnsaved(false)}
                        labelledBy="agent-unsaved-title"
                        testId="agent-unsaved-warning"
                    >
                        <div className={styles.dialogTitle} id="agent-unsaved-title">
                            Discard unsaved changes?
                        </div>
                        <div className={styles.dialogBody}>
                            You&rsquo;ve edited this agent. Leaving now discards those changes.
                        </div>
                        <div className={styles.dialogActions}>
                            <Button
                                variant="ghost"
                                onClick={() => setShowUnsaved(false)}
                                data-testid="agent-unsaved-keep"
                            >
                                Keep editing
                            </Button>
                            <Button
                                variant="danger"
                                onClick={backToList}
                                data-testid="agent-unsaved-discard"
                            >
                                Discard changes
                            </Button>
                        </div>
                    </Modal>
                )}
                <div className={styles.detailBody} data-testid="agent-detail">
                    <ProfileBuilder
                        profile={selected}
                        onSave={async (updated) => {
                            if (updated._unsaved) {
                                const { _unsaved, ...payload } = updated;
                                const created = await profilesHook.createProfile(payload);
                                if (created) {
                                    setDraft(null);
                                    setOpenId(created.id);
                                }
                                return { ok: true, data: created };
                            }
                            return profilesHook.updateProfile(updated.id, updated);
                        }}
                        onDelete={async (id) => {
                            if (draft && draft.id === id) {
                                backToList();
                                return;
                            }
                            const result = await profilesHook.deleteProfile(id);
                            if (result?.conflict) {
                                setDeleteConflict(result);
                            } else {
                                backToList();
                            }
                        }}
                        deleteConflict={deleteConflict}
                        onDismissDeleteConflict={() => setDeleteConflict(null)}
                        onDuplicate={async (id) => {
                            if (draft && draft.id === id) return;
                            const result = await profilesHook.duplicateProfile(id);
                            if (result) openAgent(result.id);
                        }}
                        onExport={() => setExportProfile(selected)}
                        onDirtyChange={setBuilderDirty}
                        providers={providers}
                        skills={skills}
                        categories={categories}
                    />
                </div>
                {exportModal}
            </div>
        );
    }

    return (
        <div className={styles.view} data-testid="agents-view">
            <div className={styles.listPane}>
                <div className={styles.toolbar}>
                    <h1 className={styles.title}>
                        <i className="bi bi-robot" /> Agents
                        <span className={styles.count}>· {visible.length}</span>
                    </h1>
                    <SearchInput
                        className={styles.search}
                        value={query}
                        onChange={setQuery}
                        placeholder="Search agents…"
                        ariaLabel="Search agents"
                        testId="agents-search"
                    />
                    <label className={styles.sortCtl}>
                        <span>Sort</span>
                        <select
                            className={styles.select}
                            value={sort.key}
                            onChange={(e) => setSort({ key: e.target.value, dir: SORTS[e.target.value].defaultDir })}
                            aria-label="Sort agents by"
                            data-testid="agents-sort"
                        >
                            {Object.entries(SORTS).map(([key, { label }]) => (
                                <option key={key} value={key}>{label}</option>
                            ))}
                        </select>
                        <IconButton
                            onClick={() => setSort((s) => ({ ...s, dir: s.dir === 'asc' ? 'desc' : 'asc' }))}
                            title={sort.dir === 'asc' ? 'Ascending' : 'Descending'}
                            aria-label="Toggle sort direction"
                            data-testid="agents-sort-dir"
                        >
                            <i className={`bi ${sort.dir === 'asc' ? 'bi-sort-down-alt' : 'bi-sort-down'}`} />
                        </IconButton>
                    </label>
                    <input
                        ref={importInputRef}
                        type="file"
                        accept=".omnideck.json,application/json"
                        style={{ display: 'none' }}
                        onChange={handleImportFile}
                        data-testid="agents-import-input"
                    />
                    <Button
                        variant="outline"
                        onClick={() => importInputRef.current?.click()}
                        data-testid="agents-import"
                    >
                        <i className="bi bi-upload" /> Import
                    </Button>
                    <Button
                        variant="filled"
                        onClick={newAgent}
                        data-testid="agents-new"
                    >
                        <i className="bi bi-plus-lg" /> New agent
                    </Button>
                </div>

                <div className={styles.scroll} data-testid="agents-list">
                    {visible.length === 0 ? (
                        <div className={styles.empty}>
                            <i className="bi bi-robot" />
                            <div>{query ? 'No agents match your search.' : 'No agents yet.'}</div>
                        </div>
                    ) : (
                        <SortableTable
                            columns={columns}
                            rows={visible}
                            rowKey={(p) => p.id}
                            sort={sort}
                            onSort={sortBy}
                            onRowClick={(p) => openAgent(p.id)}
                            rowTestId="agent-row"
                            testId="agents-table"
                        />
                    )}
                </div>
            </div>
            {exportModal}
        </div>
    );
}
