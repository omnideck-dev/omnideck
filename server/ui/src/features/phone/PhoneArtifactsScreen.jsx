import { useMemo, useState } from 'react';

import SearchInput from '../../components/primitives/SearchInput.jsx';
import { timeAgo, typeIcon } from '../../components/artifacts/_artifactUtils.js';
import useArtifacts from '../../hooks/useArtifacts.js';
import PhoneHeader from './PhoneHeader.jsx';
import styles from './PhoneArtifactsScreen.module.css';

export default function PhoneArtifactsScreen({ conversationId, conversationTitle, backLabel, onBack, onClearConversation, onOpenArtifact }) {
    const { items, loading } = useArtifacts({ conversationId });
    const [query, setQuery] = useState('');

    const shown = useMemo(() => {
        const q = query.trim().toLowerCase();
        const matched = q ? items.filter((a) => a.filename.toLowerCase().includes(q)) : items;
        return [...matched].sort((a, b) => (b.created_at || '').localeCompare(a.created_at || ''));
    }, [items, query]);

    return (
        <div className={styles.screen} data-testid="phone-artifacts">
            <PhoneHeader
                onBack={onBack}
                backLabel={backLabel}
                title={conversationId ? 'Conversation artifacts' : 'Artifacts'}
            />
            <div className={styles.tools}>
                <SearchInput
                    value={query}
                    onChange={setQuery}
                    placeholder="Search artifacts…"
                    ariaLabel="Search artifacts"
                    testId="phone-artifacts-search"
                />
                {conversationId && (
                    <button
                        type="button"
                        className={styles.filter}
                        onClick={onClearConversation}
                        title="Clear the conversation filter"
                        data-testid="phone-artifacts-clear-filter"
                    >
                        <span className={styles.filterLabel}>{conversationTitle}</span>
                        <i className="bi bi-x-lg" aria-hidden="true" />
                    </button>
                )}
            </div>
            <div className={styles.list}>
                {!loading && shown.length === 0 && (
                    <div className={styles.empty} data-testid="phone-artifacts-empty">
                        {items.length === 0 ? 'No artifacts yet.' : 'No artifacts match your search.'}
                    </div>
                )}
                {shown.map((a) => {
                    const missing = a.status === 'missing';
                    return (
                        <button
                            key={a.id}
                            type="button"
                            className={styles.row}
                            disabled={missing}
                            onClick={() => onOpenArtifact(a)}
                            data-testid="phone-artifact"
                        >
                            <i className={`bi ${typeIcon(a.content_type, a.filename)} ${styles.icon}`} aria-hidden="true" />
                            <span className={styles.body}>
                                <span className={styles.name}>{a.filename}</span>
                                <span className={styles.meta}>
                                    {missing ? 'File missing' : a.conversation_title || 'Conversation deleted'}
                                </span>
                            </span>
                            <span className={styles.when}>{timeAgo(a.created_at)}</span>
                        </button>
                    );
                })}
            </div>
        </div>
    );
}
