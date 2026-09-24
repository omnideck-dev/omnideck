import { useEffect, useRef, useState } from 'react';

const _DEFAULT_DELAY_MS = 1000;
const _DEFAULT_CHECK_MS = 400;

/**
 * Reports a stall in a streaming turn: the agent is still running but has
 * produced no new output for `delayMs`. Some providers stream a tool call's
 * arguments (e.g. a large file write) as tokens that carry no content or
 * thinking, so the turn goes silent for many seconds with nothing to render.
 * A stall lets the UI keep an activity indicator alive during that window.
 *
 * @param {string|number} activityKey — a value that advances whenever the
 *   stream emits new output (e.g. accumulated content/thinking length). Any
 *   change resets the stall clock.
 * @param {boolean} active — whether the turn is currently streaming. Stall is
 *   only reported while true.
 * @returns {boolean} true once the stream has been silent for `delayMs`.
 */
export default function useStreamStall(
    activityKey,
    active,
    { delayMs = _DEFAULT_DELAY_MS, checkMs = _DEFAULT_CHECK_MS } = {},
) {
    const [stalled, setStalled] = useState(false);
    const lastChangeRef = useRef(0);

    // New output resets the clock and clears any prior stall. setStalled(false)
    // bails without a re-render when already false, so per-token churn is free.
    useEffect(() => {
        lastChangeRef.current = Date.now();
        setStalled(false);
    }, [activityKey]);

    useEffect(() => {
        if (!active) {
            setStalled(false);
            return undefined;
        }
        // Start fresh so a stale timestamp from a prior turn can't fire an
        // immediate stall the moment streaming resumes.
        lastChangeRef.current = Date.now();
        const id = setInterval(() => {
            setStalled(Date.now() - lastChangeRef.current > delayMs);
        }, checkMs);
        return () => clearInterval(id);
    }, [active, delayMs, checkMs]);

    return active && stalled;
}
