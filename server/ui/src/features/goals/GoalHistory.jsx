import { useEffect, useRef, useState } from 'react';
import Button from '../../components/primitives/Button.jsx';
import SearchInput from '../../components/primitives/SearchInput.jsx';
import Callout from '../../components/primitives/Callout.jsx';
import DayHeader from '../../components/DayHeader.jsx';
import styles from './GoalHistory.module.css';
import { formatClockTime } from './goalStatus.js';
import { requestJson } from './GoalsState.jsx';

const ACTORS = { agent: 'Agent', user: 'You', system: 'App' };
const SEARCH_DELAY_MS = 250;

function entryDetail(entry) {
    const data = entry.data || {};
    if (entry.kind === 'answer') return data.answer;
    if (entry.kind === 'question') {
        return ({ withdrawn: 'Withdrawn.', resolved: 'Resolved.' })[data.status] || 'Asked.';
    }
    if (entry.kind === 'summary') return data.summary;
    if (entry.kind === 'plan') return (data.changes || []).join(' ');
    if (entry.kind === 'goal') return data.after?.objective || data.objective;
    if (entry.kind === 'state') {
        const next = data.after?.next;
        if (next?.kind === 'error') return next.message;
        if (next?.kind === 'done') return `Outcome: ${next.outcome}`;
    }
    return '';
}

function entryLine(entry) {
    if (entry.kind === 'question') return `Asked: ${entry.summary}`;
    if (entry.kind === 'answer') return `Answered: ${entry.summary}`;
    return entry.summary;
}

export function groupHistory(entries) {
    const groups = [];
    const byRun = new Map();
    for (const entry of entries) {
        const run = entry.claim_id;
        if (run && byRun.has(run)) {
            byRun.get(run).entries.push(entry);
            continue;
        }
        const group = { id: entry.id, run, entries: [entry] };
        groups.push(group);
        if (run) byRun.set(run, group);
    }
    return groups.map((group) => {
        if (!group.run) {
            const [entry] = group.entries;
            return { id: group.id, created_at: entry.created_at, actor: entry.actor, line: entryLine(entry), detail: entryDetail(entry), details: [] };
        }
        const note = group.entries.find((entry) => entry.kind === 'note');
        const ending = group.entries.find((entry) => entry.kind === 'state' && entry.actor !== 'agent');
        const main = note || ending || group.entries[0];
        const details = group.entries.filter((entry) => entry !== main).map((entry) => ({
            id: entry.id, line: entryLine(entry), detail: entryDetail(entry),
        }));
        return {
            id: group.id, created_at: group.entries[0].created_at, actor: main.actor,
            line: note || ending ? entryLine(main) : 'Worked on the goal.',
            detail: note || ending ? entryDetail(main) : '', details: note || ending ? details : [{ id: main.id, line: entryLine(main), detail: entryDetail(main) }, ...details],
        };
    });
}

export default function GoalHistory({ conversationId, goalId, revision, open, onOpenChange }) {
    const [query, setQuery] = useState('');
    const [search, setSearch] = useState('');
    const [page, setPage] = useState({ entries: [], next_before: null });
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState('');
    const generation = useRef(0);
    const mounted = useRef(true);
    useEffect(() => {
        mounted.current = true;
        return () => { mounted.current = false; generation.current += 1; };
    }, []);
    useEffect(() => {
        const timer = setTimeout(() => setSearch(query.trim()), SEARCH_DELAY_MS);
        return () => clearTimeout(timer);
    }, [query]);

    async function load(before, version) {
        setBusy(true);
        setError('');
        try {
            const params = new URLSearchParams({ goal_id: goalId, q: search });
            if (before) params.set('before', before);
            const data = await requestJson(`/api/conversations/sessions/${encodeURIComponent(conversationId)}/goal/history?${params}`, undefined, 'Could not load goal history.');
            if (!mounted.current || generation.current !== version) return;
            setPage((current) => ({ ...data, entries: before ? [...current.entries, ...data.entries] : data.entries }));
        } catch (failure) {
            if (mounted.current && generation.current === version) setError(failure.message);
        } finally {
            if (mounted.current && generation.current === version) setBusy(false);
        }
    }
    useEffect(() => {
        const version = ++generation.current;
        if (open) void load(null, version);
    }, [open, search, goalId, conversationId, revision]);

    const groups = groupHistory(page.entries);
    let lastDay = null;
    return <details open={open} onToggle={(event) => onOpenChange(event.currentTarget.open)}>
        <summary className={styles.disclosure}>Goal history</summary>
        {open && <section className={styles.historyEntries} aria-label="Goal history entries">
            <SearchInput className={styles.historySearch} value={query} onChange={setQuery} ariaLabel="Search goal history" placeholder="Search goal history" />
            {error && <Callout tone="warning" title={error} />}
            <ol className={styles.progress}>{groups.map((group) => {
                const day = new Date(group.created_at).toDateString();
                const header = day !== lastDay ? <DayHeader timestamp={group.created_at} /> : null;
                lastDay = day;
                return <li key={group.id} data-testid="goal-history-entry">
                    {header}
                    <div className={styles.historyLine}>
                        <time dateTime={group.created_at} title={new Date(group.created_at).toLocaleString()}>{formatClockTime(group.created_at)}</time>
                        <span className={styles.historyActor}>{ACTORS[group.actor] || 'App'}</span>
                        <span>{group.line}</span>
                    </div>
                    {group.detail && <p className={styles.historyDetail}>{group.detail}</p>}
                    {group.details.length > 0 && <details className={styles.historyFold}>
                        <summary className={styles.disclosure}>Details</summary>
                        <ul className={styles.historyDetails}>{group.details.map((item) => <li key={item.id}>
                            {item.line}{item.detail ? <span className={styles.historyDetail}> {item.detail}</span> : null}
                        </li>)}</ul>
                    </details>}
                </li>;
            })}</ol>
            {!busy && !error && !page.entries.length && <p className={styles.description}>{search ? 'No history matches this search.' : 'No history yet.'}</p>}
            {busy && !page.entries.length && <p role="status" className={styles.description}>Loading history…</p>}
            {page.next_before && <Button variant="ghost" disabled={busy} onClick={() => load(page.next_before, generation.current)}>Load older entries</Button>}
        </section>}
    </details>;
}
