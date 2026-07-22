import { useEffect, useMemo, useRef, useState } from 'react';
import useBrowserControl from './useBrowserControl.js';

/**
 * Owns the browser side channel and the tab model the workspace renders.
 *
 * Wraps useBrowserControl and adds the two-source tab list (the live channel
 * list during takeover, falling back to the agent's screenshot-fed list) and
 * the selected-tab state that drives which tab is foregrounded and screencast.
 * Selection feeds back into the control channel, so both live here to keep that
 * loop in one place instead of in the app shell.
 *
 * Returns the control object, the merged tab list, and the selection state.
 */
export default function useBrowserTabs({ conversationId, canControl, enabled, agentTabs }) {
    const [selectedTabId, setSelectedTabId] = useState(null);

    const control = useBrowserControl({ conversationId, selectedTabId, canControl, enabled });

    // Prefer the live channel list once it has sent anything (fresh during
    // takeover, when the agent emits no screenshots), reusing agent screenshots
    // as thumbnails. `null` means the channel hasn't reported yet — fall back to
    // the agent list; an empty array is authoritative "zero tabs", not a gap.
    const tabs = useMemo(() => {
        const live = control.liveTabs;
        if (live == null) return agentTabs;
        const snapById = new Map(agentTabs.map((t) => [t.id, t.snapshot]));
        return live.map((t) => ({
            id: t.id,
            snapshot: {
                url: t.url,
                title: t.title,
                screenshot: snapById.get(t.id)?.screenshot || null,
            },
        }));
    }, [control.liveTabs, agentTabs]);

    // Sticky selection: keep the chosen tab if still open, else fall back to the
    // first. The selected tab is the one foregrounded + screencast.
    useEffect(() => {
        const ids = tabs.map((t) => t.id);
        setSelectedTabId((prev) => (prev != null && ids.includes(prev)) ? prev : (ids[0] ?? null));
    }, [tabs]);

    // While engaged, any newly opened tab is human-initiated → follow it.
    const prevIds = useRef([]);
    useEffect(() => {
        const ids = (control.liveTabs || []).map((t) => t.id);
        const added = ids.filter((id) => !prevIds.current.includes(id));
        prevIds.current = ids;
        if (control.engaged && added.length) {
            setSelectedTabId(Math.max(...added));
        }
    }, [control.liveTabs, control.engaged]);

    return { control, tabs, selectedTabId, setSelectedTabId };
}
