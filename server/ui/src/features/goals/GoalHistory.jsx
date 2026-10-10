import { useEffect, useRef, useState } from 'react';
import Button from '../../components/primitives/Button.jsx';
import SearchInput from '../../components/primitives/SearchInput.jsx';
import Callout from '../../components/primitives/Callout.jsx';
import styles from './GoalPanel.module.css';

function EntryDetails({ entry }) {
    const data = entry.data;
    if (entry.kind === 'answer') return <p className={styles.prose}>{data.answer}</p>;
    if (entry.kind === 'question') return <p className={styles.description}>{data.status === 'withdrawn' ? 'No longer needed' : data.status === 'resolved' ? 'Resolved' : 'Asked'} · Revision {data.revision}</p>;
    if (entry.kind === 'progress') return data.next_action && <p className={styles.description}>Next: {data.next_action}</p>;
    if (entry.kind === 'plan') return <details><summary className={styles.disclosure}>Plan at this point</summary><ol className={styles.plan}>{data.after.plan.map((step) => <li key={step.id}><p>{step.title} · {step.status.replace('_', ' ')}</p>{step.notes && <p className={styles.description}>{step.notes}</p>}</li>)}</ol></details>;
    const values = data.after || data;
    return <div>{Object.entries(values).filter(([, value]) => value !== null && value !== '' && (!Array.isArray(value) || value.length)).map(([key, value]) => <p className={styles.prose} key={key}><span className={styles.description}>{key.replaceAll('_', ' ')}: </span>{Array.isArray(value) ? value.join(', ') : String(value)}</p>)}</div>;
}

export default function GoalHistory({ conversationId, goalId }) {
    const [open, setOpen] = useState(false);
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

    async function load(before, version) {
        setBusy(true);
        setError('');
        try {
            const params = new URLSearchParams({ goal_id: goalId, q: search });
            if (before) params.set('before', before);
            const response = await fetch(`/api/conversations/sessions/${encodeURIComponent(conversationId)}/goal/history?${params}`);
            const data = await response.json();
            if (!response.ok) throw new Error(data.error || 'Could not load goal history.');
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
        if (open) {
            setPage({ entries: [], next_before: null });
            void load(null, version);
        }
    }, [open, search, goalId, conversationId]);

    return <details open={open} onToggle={(event) => setOpen(event.currentTarget.open)}>
        <summary className={styles.disclosure}>Goal history</summary>
        {open && <section aria-label="Goal history entries">
            <form className={styles.actions} onSubmit={(event) => { event.preventDefault(); setSearch(query.trim()); }}>
                <SearchInput value={query} onChange={setQuery} ariaLabel="Search goal history" placeholder="Search decisions, progress, answers…" />
                <Button variant="ghost" type="submit" disabled={busy}>Search</Button>
                <Button variant="ghost" disabled={busy} onClick={() => load(null, ++generation.current)}>Refresh</Button>
            </form>
            {error && <Callout tone="warning" title={error} />}
            <ol className={styles.progress}>{page.entries.map((entry) => <li key={entry.id}>
                <time dateTime={entry.created_at}>{new Date(entry.created_at).toLocaleString()}</time>
                <p>{entry.summary}</p><EntryDetails entry={entry} />
            </li>)}</ol>
            {!busy && !error && !page.entries.length && <p className={styles.description}>No history matches this search.</p>}
            {busy && <p role="status" className={styles.description}>Loading history…</p>}
            {page.next_before && <Button variant="ghost" disabled={busy} onClick={() => load(page.next_before, generation.current)}>Load older entries</Button>}
        </section>}
    </details>;
}
