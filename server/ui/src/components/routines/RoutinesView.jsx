import { useState, useEffect, useMemo } from 'react';

import Badge from '../Badge.jsx';
import Button from '../primitives/Button.jsx';
import IconButton from '../primitives/IconButton.jsx';
import RowDeleteButton from '../primitives/RowDeleteButton.jsx';
import SearchInput from '../primitives/SearchInput.jsx';
import Select from '../primitives/Select.jsx';
import SortableTable from '../primitives/SortableTable.jsx';
import StarterPrompts from '../StarterPrompts.jsx';
import useRoutines from '../../hooks/useRoutines.js';
import RoutineDetailPanel from './RoutineDetailPanel.jsx';
import { formatCron, formatTime } from './routineUtils.jsx';
import styles from './RoutinesView.module.css';

// Working order for the status sort: running/active surface first.
const STATUS_ORDER = { running: 0, active: 1, pending: 2, paused: 3, completed: 4, failed: 5 };

const displayStatusOf = (g) => (g.is_running ? 'running' : g.status);

// Sortable columns, also shown in the toolbar's sort select.
const SORTS = {
    name: { label: 'Name', defaultDir: 'asc', value: (g) => (g.description || '').toLowerCase() },
    status: { label: 'Status', defaultDir: 'asc', value: (g) => STATUS_ORDER[displayStatusOf(g)] ?? 5 },
    recent: { label: 'Last run', defaultDir: 'desc', value: (g) => new Date(g.last_run_at || 0).getTime() },
};

// Empty-state suggestions — real consumer routines grounded in the agent's tools
// (email, calendar, web research, file generation). Clicking one opens a new
// chat with that text prefilled.
// Phrased as "Create a routine that…" on purpose: without it the agent just runs
// the task once instead of setting up the recurring routine.
const ROUTINE_PROMPTS = [
    {
        icon: 'bi-envelope',
        title: 'Daily email digest',
        text: 'Create a routine that every weekday at 8am summarizes my unread email into a short digest.',
    },
    {
        icon: 'bi-calendar-event',
        title: 'Morning agenda',
        text: "Create a routine that each morning briefs me on today's calendar and flags anything I should prep for.",
    },
    {
        icon: 'bi-file-earmark-text',
        title: 'Weekly research report',
        text: "Create a routine that every Monday compiles a PDF of the past week's biggest AI developments and emails it to me.",
    },
    {
        icon: 'bi-binoculars',
        title: 'Watch the web',
        text: 'Create a routine that each evening checks the websites I follow and tells me what changed.',
    },
];

/**
 * Routines view: a sortable table that owns the full width until a routine is
 * selected, then the routine opens full-width with a back nav. Self-contained —
 * it owns its routines state via useRoutines; the toolbar carries title + count,
 * search, and sort, mirroring the artifacts hub.
 */
export default function RoutinesView({ onComposeInChat }) {
    const {
        routines,
        selectedRoutineId,
        setSelectedRoutineId,
        fetchRoutineDetail,
        deleteRoutine,
        deleteRun,
        pauseRoutine,
        resumeRoutine,
        triggerRoutine,
    } = useRoutines(true);

    const [detail, setDetail] = useState(null);
    const [isLoading, setIsLoading] = useState(false);
    const [error, setError] = useState(null);
    const [refreshCounter, setRefreshCounter] = useState(0);
    const [query, setQuery] = useState('');
    const [sort, setSort] = useState({ key: 'status', dir: 'asc' });

    useEffect(() => {
        if (!selectedRoutineId) {
            setDetail(null);
            setError(null);
            return undefined;
        }
        setIsLoading(true);
        setError(null);
        fetchRoutineDetail(selectedRoutineId)
            .then((data) => { setDetail(data); })
            .catch((err) => { setError(err.message); setDetail(null); })
            .finally(() => { setIsLoading(false); });
        return undefined;
    }, [selectedRoutineId, fetchRoutineDetail, refreshCounter]);

    useEffect(() => {
        if (!selectedRoutineId) return undefined;
        const interval = setInterval(() => {
            fetchRoutineDetail(selectedRoutineId).then((data) => setDetail(data)).catch(() => {});
        }, 5000);
        return () => clearInterval(interval);
    }, [selectedRoutineId, fetchRoutineDetail]);

    const refresh = () => setRefreshCounter((c) => c + 1);
    const handleTrigger = async (id) => { await triggerRoutine(id); refresh(); };
    const handlePause = async (id) => { await pauseRoutine(id); refresh(); };
    const handleResume = async (id) => { await resumeRoutine(id); refresh(); };
    const handleDelete = async (id) => { await deleteRoutine(id); setSelectedRoutineId(null); };
    const handleDeleteRun = async (id, runId) => { await deleteRun(id, runId); refresh(); };

    const visible = useMemo(() => {
        const q = query.trim().toLowerCase();
        const matched = q
            ? routines.filter((g) => (g.description || '').toLowerCase().includes(q))
            : routines;
        const value = SORTS[sort.key].value;
        const dir = sort.dir === 'asc' ? 1 : -1;
        return [...matched].sort((a, b) => {
            const av = value(a);
            const bv = value(b);
            if (av < bv) return -dir;
            if (av > bv) return dir;
            return (a.description || '').localeCompare(b.description || '');
        });
    }, [routines, query, sort]);

    function sortBy(key) {
        setSort((s) => (s.key === key
            ? { key, dir: s.dir === 'asc' ? 'desc' : 'asc' }
            : { key, dir: SORTS[key].defaultDir }));
    }

    const columns = [
        { key: 'name', header: 'Name', sortable: true, cellClassName: styles.gname, render: (g) => g.description },
        { key: 'status', header: 'Status', sortable: true, render: (g) => <StatusBadge status={displayStatusOf(g)} /> },
        {
            key: 'schedule',
            header: 'Schedule',
            cellClassName: styles.schedule,
            render: (g) => (g.cron
                ? <span title={g.cron}>{formatCron(g.cron)}</span>
                : <span className={styles.muted}>—</span>),
        },
        {
            key: 'recent',
            header: 'Last run',
            sortable: true,
            cellClassName: styles.when,
            render: (g) => (g.last_run_at
                ? formatTime(g.last_run_at)
                : <span className={styles.muted}>—</span>),
        },
        {
            key: 'actions',
            header: '',
            cellClassName: styles.acts,
            revealOnHover: true,
            render: (g) => (
                <RowDeleteButton
                    title="Delete routine"
                    data-testid="routine-delete"
                    onConfirm={() => handleDelete(g.id)}
                />
            ),
        },
    ];

    const selectedRoutine = routines.find((g) => g.id === selectedRoutineId) || null;

    // Selecting a routine replaces the list with its full detail; a back nav in the
    // header returns to the list. Full-width either way — the sortable table and
    // the detail's runs table both need the room.
    if (selectedRoutine) {
        return (
            <div className={styles.view} data-testid="routines-view">
                <div className={styles.detailHead}>
                    <Button
                        variant="ghost"
                        onClick={() => setSelectedRoutineId(null)}
                        data-testid="routine-detail-back"
                    >
                        <i className="bi bi-arrow-left" /> Routines
                    </Button>
                </div>
                {error && <div className={styles.errorBanner}>Error loading routine: {error}</div>}
                <div className={styles.detailBody} data-testid="routine-detail">
                    <RoutineDetailPanel
                        routine={selectedRoutine}
                        detail={detail}
                        isLoading={isLoading}
                        onDeleteRoutine={handleDelete}
                        onDeleteRun={handleDeleteRun}
                        onPauseRoutine={handlePause}
                        onResumeRoutine={handleResume}
                        onTriggerRoutine={handleTrigger}
                    />
                </div>
            </div>
        );
    }

    // No routines at all: a full-screen prompt to create one by talking to the
    // agent. The example opens a fresh chat with the composer pre-seeded.
    if (routines.length === 0) {
        return (
            <div className={styles.view} data-testid="routines-view">
                <div className={styles.emptyState} data-testid="routines-empty">
                    <StarterPrompts
                        heading="No routines yet"
                        subheading="Routines let the agent run recurring work for you on a schedule. Pick one to get started — or describe your own in chat."
                        prompts={ROUTINE_PROMPTS}
                        onSelect={(text) => onComposeInChat?.(text)}
                    />
                </div>
            </div>
        );
    }

    return (
        <div className={styles.view} data-testid="routines-view">
            <div className={styles.listPane}>
                <div className={styles.toolbar}>
                    <h1 className={styles.title}>
                        <i className="bi bi-bullseye" /> Routines
                        <span className={styles.count}>· {visible.length}</span>
                    </h1>
                    <SearchInput
                        className={styles.search}
                        value={query}
                        onChange={setQuery}
                        placeholder="Search routines…"
                        ariaLabel="Search routines"
                        testId="routines-search"
                    />
                    <div className={styles.sortCtl}>
                        <span>Sort</span>
                        <Select
                            className={styles.select}
                            value={sort.key}
                            onChange={(key) => setSort({ key, dir: SORTS[key].defaultDir })}
                            ariaLabel="Sort routines by"
                            testId="routines-sort"
                            options={Object.entries(SORTS).map(([key, { label }]) => ({ value: key, label }))}
                        />
                        <IconButton
                            onClick={() => setSort((s) => ({ ...s, dir: s.dir === 'asc' ? 'desc' : 'asc' }))}
                            title={sort.dir === 'asc' ? 'Ascending' : 'Descending'}
                            aria-label="Toggle sort direction"
                            data-testid="routines-sort-dir"
                        >
                            <i className={`bi ${sort.dir === 'asc' ? 'bi-sort-down-alt' : 'bi-sort-down'}`} />
                        </IconButton>
                    </div>
                </div>

                <div className={styles.scroll} data-testid="routines-list">
                    {visible.length === 0 ? (
                        <div className={styles.empty}>
                            <i className="bi bi-bullseye" />
                            <div>No routines match your search.</div>
                        </div>
                    ) : (
                        <SortableTable
                            columns={columns}
                            rows={visible}
                            rowKey={(g) => g.id}
                            sort={sort}
                            onSort={sortBy}
                            onRowClick={(g) => setSelectedRoutineId(g.id)}
                            rowTestId="routine-row"
                            testId="routines-table"
                        />
                    )}
                </div>
            </div>
        </div>
    );
}

function StatusBadge({ status }) {
    const variants = {
        running: { variant: 'info', label: 'RUNNING' },
        active: { variant: 'success', label: 'ACTIVE' },
        completed: { variant: 'success', label: 'COMPLETE' },
        failed: { variant: 'danger', label: 'ERROR' },
        paused: { variant: 'neutral', label: 'PAUSED' },
        pending: { variant: 'neutral', label: 'PENDING' },
    };
    const v = variants[status] || { variant: 'neutral', label: String(status || '').toUpperCase() };
    return <Badge variant={v.variant}>{v.label}</Badge>;
}
