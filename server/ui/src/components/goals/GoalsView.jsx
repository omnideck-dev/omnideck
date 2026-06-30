import { useState, useEffect, useMemo } from 'react';

import Badge from '../Badge.jsx';
import Button from '../primitives/Button.jsx';
import IconButton from '../primitives/IconButton.jsx';
import SearchInput from '../primitives/SearchInput.jsx';
import SortableTable from '../primitives/SortableTable.jsx';
import StarterPrompts from '../StarterPrompts.jsx';
import useGoals from '../../hooks/useGoals.js';
import GoalDetailPanel from './GoalDetailPanel.jsx';
import { formatCron, formatTime } from './goalUtils.jsx';
import styles from './GoalsView.module.css';

// Working order for the status sort: running/active surface first.
const STATUS_ORDER = { running: 0, active: 1, pending: 2, paused: 3, completed: 4, failed: 5 };

const displayStatusOf = (g) => (g.is_running ? 'running' : g.status);

// Sortable columns, also shown in the toolbar's sort select.
const SORTS = {
    name: { label: 'Name', defaultDir: 'asc', value: (g) => (g.description || '').toLowerCase() },
    status: { label: 'Status', defaultDir: 'asc', value: (g) => STATUS_ORDER[displayStatusOf(g)] ?? 5 },
    recent: { label: 'Last run', defaultDir: 'desc', value: (g) => new Date(g.last_run_at || 0).getTime() },
};

// Empty-state suggestions — real consumer goals grounded in the agent's tools
// (email, calendar, web research, file generation). Clicking one opens a new
// chat with that text prefilled.
// Phrased as "Create a goal that…" on purpose: without it the agent just runs
// the task once instead of setting up the recurring goal.
const GOAL_PROMPTS = [
    {
        icon: 'bi-envelope',
        title: 'Daily email digest',
        text: 'Create a goal that every weekday at 8am summarizes my unread email into a short digest.',
    },
    {
        icon: 'bi-calendar-event',
        title: 'Morning agenda',
        text: "Create a goal that each morning briefs me on today's calendar and flags anything I should prep for.",
    },
    {
        icon: 'bi-file-earmark-text',
        title: 'Weekly research report',
        text: "Create a goal that every Monday compiles a PDF of the past week's biggest AI developments and emails it to me.",
    },
    {
        icon: 'bi-binoculars',
        title: 'Watch the web',
        text: 'Create a goal that each evening checks the websites I follow and tells me what changed.',
    },
];

/**
 * Goals view: a sortable table that owns the full width until a goal is
 * selected, then the goal opens full-width with a back nav. Self-contained —
 * it owns its goals state via useGoals; the toolbar carries title + count,
 * search, and sort, mirroring the artifacts hub.
 */
export default function GoalsView({ onComposeInChat }) {
    const {
        goals,
        selectedGoalId,
        setSelectedGoalId,
        fetchGoalDetail,
        deleteGoal,
        deleteRun,
        pauseGoal,
        resumeGoal,
        triggerGoal,
    } = useGoals(true);

    const [detail, setDetail] = useState(null);
    const [isLoading, setIsLoading] = useState(false);
    const [error, setError] = useState(null);
    const [refreshCounter, setRefreshCounter] = useState(0);
    const [query, setQuery] = useState('');
    const [sort, setSort] = useState({ key: 'status', dir: 'asc' });

    useEffect(() => {
        if (!selectedGoalId) {
            setDetail(null);
            setError(null);
            return undefined;
        }
        setIsLoading(true);
        setError(null);
        fetchGoalDetail(selectedGoalId)
            .then((data) => { setDetail(data); })
            .catch((err) => { setError(err.message); setDetail(null); })
            .finally(() => { setIsLoading(false); });
        return undefined;
    }, [selectedGoalId, fetchGoalDetail, refreshCounter]);

    useEffect(() => {
        if (!selectedGoalId) return undefined;
        const interval = setInterval(() => {
            fetchGoalDetail(selectedGoalId).then((data) => setDetail(data)).catch(() => {});
        }, 5000);
        return () => clearInterval(interval);
    }, [selectedGoalId, fetchGoalDetail]);

    const refresh = () => setRefreshCounter((c) => c + 1);
    const handleTrigger = async (id) => { await triggerGoal(id); refresh(); };
    const handlePause = async (id) => { await pauseGoal(id); refresh(); };
    const handleResume = async (id) => { await resumeGoal(id); refresh(); };
    const handleDelete = async (id) => { await deleteGoal(id); setSelectedGoalId(null); };
    const handleDeleteRun = async (id, runId) => { await deleteRun(id, runId); refresh(); };

    const visible = useMemo(() => {
        const q = query.trim().toLowerCase();
        const matched = q
            ? goals.filter((g) => (g.description || '').toLowerCase().includes(q))
            : goals;
        const value = SORTS[sort.key].value;
        const dir = sort.dir === 'asc' ? 1 : -1;
        return [...matched].sort((a, b) => {
            const av = value(a);
            const bv = value(b);
            if (av < bv) return -dir;
            if (av > bv) return dir;
            return (a.description || '').localeCompare(b.description || '');
        });
    }, [goals, query, sort]);

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
    ];

    const selectedGoal = goals.find((g) => g.id === selectedGoalId) || null;

    // Selecting a goal replaces the list with its full detail; a back nav in the
    // header returns to the list. Full-width either way — the sortable table and
    // the detail's runs table both need the room.
    if (selectedGoal) {
        return (
            <div className={styles.view} data-testid="goals-view">
                <div className={styles.detailHead}>
                    <Button
                        variant="ghost"
                        onClick={() => setSelectedGoalId(null)}
                        data-testid="goal-detail-back"
                    >
                        <i className="bi bi-arrow-left" /> Goals
                    </Button>
                </div>
                {error && <div className={styles.errorBanner}>Error loading goal: {error}</div>}
                <div className={styles.detailBody} data-testid="goal-detail">
                    <GoalDetailPanel
                        goal={selectedGoal}
                        detail={detail}
                        isLoading={isLoading}
                        onDeleteGoal={handleDelete}
                        onDeleteRun={handleDeleteRun}
                        onPauseGoal={handlePause}
                        onResumeGoal={handleResume}
                        onTriggerGoal={handleTrigger}
                    />
                </div>
            </div>
        );
    }

    // No goals at all: a full-screen prompt to create one by talking to the
    // agent. The example opens a fresh chat with the composer pre-seeded.
    if (goals.length === 0) {
        return (
            <div className={styles.view} data-testid="goals-view">
                <div className={styles.emptyState} data-testid="goals-empty">
                    <StarterPrompts
                        heading="No goals yet"
                        subheading="Goals let the agent run recurring work for you on a schedule. Pick one to get started — or describe your own in chat."
                        prompts={GOAL_PROMPTS}
                        onSelect={(text) => onComposeInChat?.(text)}
                    />
                </div>
            </div>
        );
    }

    return (
        <div className={styles.view} data-testid="goals-view">
            <div className={styles.listPane}>
                <div className={styles.toolbar}>
                    <h1 className={styles.title}>
                        <i className="bi bi-bullseye" /> Goals
                        <span className={styles.count}>· {visible.length}</span>
                    </h1>
                    <SearchInput
                        className={styles.search}
                        value={query}
                        onChange={setQuery}
                        placeholder="Search goals…"
                        ariaLabel="Search goals"
                        testId="goals-search"
                    />
                    <label className={styles.sortCtl}>
                        <span>Sort</span>
                        <select
                            className={styles.select}
                            value={sort.key}
                            onChange={(e) => setSort({ key: e.target.value, dir: SORTS[e.target.value].defaultDir })}
                            aria-label="Sort goals by"
                            data-testid="goals-sort"
                        >
                            {Object.entries(SORTS).map(([key, { label }]) => (
                                <option key={key} value={key}>{label}</option>
                            ))}
                        </select>
                        <IconButton
                            onClick={() => setSort((s) => ({ ...s, dir: s.dir === 'asc' ? 'desc' : 'asc' }))}
                            title={sort.dir === 'asc' ? 'Ascending' : 'Descending'}
                            aria-label="Toggle sort direction"
                            data-testid="goals-sort-dir"
                        >
                            <i className={`bi ${sort.dir === 'asc' ? 'bi-sort-down-alt' : 'bi-sort-down'}`} />
                        </IconButton>
                    </label>
                </div>

                <div className={styles.scroll} data-testid="goals-list">
                    {visible.length === 0 ? (
                        <div className={styles.empty}>
                            <i className="bi bi-bullseye" />
                            <div>No goals match your search.</div>
                        </div>
                    ) : (
                        <SortableTable
                            columns={columns}
                            rows={visible}
                            rowKey={(g) => g.id}
                            sort={sort}
                            onSort={sortBy}
                            onRowClick={(g) => setSelectedGoalId(g.id)}
                            rowTestId="goal-row"
                            testId="goals-table"
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
