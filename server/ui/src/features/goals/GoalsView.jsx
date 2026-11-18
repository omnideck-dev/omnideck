import { useMemo, useState } from 'react';

import { timeAgo } from '../../components/artifacts/_artifactUtils.js';
import { label as conversationLabel } from '../../components/conversationSections.js';
import Button from '../../components/primitives/Button.jsx';
import IconButton from '../../components/primitives/IconButton.jsx';
import SearchInput from '../../components/primitives/SearchInput.jsx';
import Select from '../../components/primitives/Select.jsx';
import SortableTable from '../../components/primitives/SortableTable.jsx';
import StarterPrompts, { AccentWord } from '../../components/StarterPrompts.jsx';
import { useConversationCatalog } from '../conversation/catalog/ConversationCatalog.jsx';
import GoalStatus from './GoalStatus.jsx';
import { useGoals } from './GoalsState.jsx';
import { goalStatus, planProgress } from './goalStatus.js';
import styles from './GoalsView.module.css';

const STATUS_ORDER = ['questions', 'waiting', 'error', 'working', 'starting', 'scheduled', 'paused', 'done', 'cancelled'];

const SORTS = {
    status: { label: 'Status', defaultDir: 'asc' },
    updated: { label: 'Last update', defaultDir: 'desc' },
    name: { label: 'Name', defaultDir: 'asc' },
};

export const GOAL_PROMPTS = [
    { icon: 'bi-airplane', title: 'Plan a trip', text: 'Plan a 4-day trip to Chicago in May for two. Ask me about budget and dates.' },
    { icon: 'bi-tag', title: 'Watch a price', text: 'Check the price of the Sony WH-1000XM5 every morning and tell me when it drops below $300.' },
    { icon: 'bi-house', title: 'Find a contractor', text: 'Find three roofers near me with good reviews and get quotes for a roof repair.' },
    { icon: 'bi-journal-text', title: 'Research a topic', text: 'Research heat pumps for a 1950s house and write me a one-page summary with costs.' },
];

function compareRows(key, a, b) {
    if (key === 'updated') return Date.parse(a.goal.updated_at || 0) - Date.parse(b.goal.updated_at || 0);
    if (key === 'name') return a.goal.objective.localeCompare(b.goal.objective);
    const rank = STATUS_ORDER.indexOf(a.status.key) - STATUS_ORDER.indexOf(b.status.key);
    if (rank) return rank;
    if (a.status.key === 'scheduled') {
        const soon = Date.parse(a.goal.next.at) - Date.parse(b.goal.next.at);
        if (soon) return soon;
    }
    return a.goal.objective.localeCompare(b.goal.objective);
}

function PlanCell({ goal }) {
    const { done, total } = planProgress(goal);
    if (!total) return <span className={styles.muted}>—</span>;
    return <span className={styles.plan}>
        <span className={styles.bar} role="progressbar" aria-label="Plan progress" aria-valuemin={0} aria-valuemax={total} aria-valuenow={done}>
            <span className={styles.barFill} style={{ width: `${Math.round((done / total) * 100)}%` }} />
        </span>
        <span className={styles.count}>{done} of {total}</span>
    </span>;
}

/** Every chat's latest goal. Picking one opens its chat and Goal tab. */
export default function GoalsView({ onOpenGoal, onStartGoal }) {
    const { goalsByConversation } = useGoals();
    const { items, loading } = useConversationCatalog();
    const [query, setQuery] = useState('');
    const [sort, setSort] = useState({ key: 'status', dir: 'asc' });

    const rows = useMemo(() => items.flatMap((item) => {
        const goal = goalsByConversation[item.conversation_id];
        return goal ? [{ id: item.conversation_id, goal, title: conversationLabel(item), status: goalStatus(goal) }] : [];
    }), [items, goalsByConversation]);

    const visible = useMemo(() => {
        const needle = query.trim().toLowerCase();
        const matching = needle
            ? rows.filter((row) => row.goal.objective.toLowerCase().includes(needle) || row.title.toLowerCase().includes(needle))
            : rows;
        const direction = sort.dir === 'asc' ? 1 : -1;
        return [...matching].sort((a, b) => direction * compareRows(sort.key, a, b));
    }, [rows, query, sort]);

    const sortBy = (key) => setSort((current) => (current.key === key
        ? { key, dir: current.dir === 'asc' ? 'desc' : 'asc' }
        : { key, dir: SORTS[key].defaultDir }));

    const startButton = <Button variant="filled" onClick={() => onStartGoal('')} data-testid="goals-start">
        <i className="bi bi-bullseye" aria-hidden="true" /> Start a goal…
    </Button>;

    if (!loading && rows.length === 0) {
        return <div className={styles.view} data-testid="goals-view">
            <div className={styles.emptyState} data-testid="goals-empty">
                <StarterPrompts
                    heading={<>No goals <AccentWord>yet</AccentWord></>}
                    subheading="A goal is a longer task the agent keeps working on in its own chat. It makes a plan, can ask you questions, and comes back later on its own. Pick an example, or start your own."
                    prompts={GOAL_PROMPTS}
                    onSelect={(text) => onStartGoal(text)}
                />
                <div className={styles.emptyAction}>{startButton}</div>
            </div>
        </div>;
    }

    const columns = [
        {
            key: 'name', header: 'Goal', sortable: true,
            render: (row) => <span className={styles.goalCell}>
                <span className={styles.objective}>{row.goal.objective}</span>
                <span className={styles.chat}><i className="bi bi-chat-left-text" aria-hidden="true" /> {row.title}</span>
            </span>,
        },
        { key: 'status', header: 'Status', sortable: true, render: (row) => <GoalStatus goal={row.goal} compact /> },
        { key: 'plan', header: 'Plan', render: (row) => <PlanCell goal={row.goal} /> },
        {
            key: 'updated', header: 'Last update', sortable: true, cellClassName: styles.when,
            render: (row) => <span title={row.goal.updated_at}>{timeAgo(row.goal.updated_at)}</span>,
        },
    ];

    return <div className={styles.view} data-testid="goals-view">
        <div className={styles.toolbar}>
            <h1 className={styles.title}>
                <i className="bi bi-bullseye" /> Goals
                <span className={styles.titleCount}>· {visible.length}</span>
            </h1>
            <SearchInput className={styles.search} value={query} onChange={setQuery}
                placeholder="Search goals…" ariaLabel="Search goals" testId="goals-search" />
            <div className={styles.sortCtl}>
                <span>Sort</span>
                <Select className={styles.select} value={sort.key} onChange={(key) => setSort({ key, dir: SORTS[key].defaultDir })}
                    ariaLabel="Sort goals by" testId="goals-sort"
                    options={Object.entries(SORTS).map(([key, { label }]) => ({ value: key, label }))} />
                <IconButton onClick={() => setSort((current) => ({ ...current, dir: current.dir === 'asc' ? 'desc' : 'asc' }))}
                    title={sort.dir === 'asc' ? 'Ascending' : 'Descending'} aria-label="Toggle sort direction" data-testid="goals-sort-dir">
                    <i className={`bi ${sort.dir === 'asc' ? 'bi-sort-down-alt' : 'bi-sort-down'}`} />
                </IconButton>
            </div>
            {startButton}
        </div>
        <div className={styles.scroll} data-testid="goals-list">
            {visible.length === 0
                ? <div className={styles.empty}><i className="bi bi-bullseye" /><div>No goals match your search.</div></div>
                : <SortableTable columns={columns} rows={visible} rowKey={(row) => row.id} sort={sort} onSort={sortBy}
                    onRowClick={(row) => onOpenGoal(row.id)} rowTestId="goal-row" testId="goals-table" />}
        </div>
    </div>;
}
