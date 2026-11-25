import { useCallback, useEffect, useState } from 'react';

import useLiveConversationList from './useLiveConversationList.js';

/** The archived chats, loaded up front so their count shows on the collapsed header, and kept current live. */
export default function useArchivedConversations() {
    const [archived, setArchived] = useState([]);
    const [archivedLoaded, setArchivedLoaded] = useState(false);
    const load = useCallback(() => fetch('/api/conversations/archived')
        .then((r) => (r.ok ? r.json() : null))
        .then((data) => { if (data) setArchived(data); })
        .catch(() => {})
        .finally(() => setArchivedLoaded(true)), []);
    useEffect(() => { void load(); }, [load]);
    useLiveConversationList({ setItems: setArchived, refetch: load, archived: true });
    return { archived, setArchived, archivedLoaded };
}
