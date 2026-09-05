/**
 * Carries Browser screencast frames from the socket to the canvas without React.
 *
 * A live view repaints at the page's own rate. Routing that through component
 * state re-renders the whole app on every frame, so frames go through this
 * plain object instead: the socket pushes, the viewport subscribes, and React
 * only ever sees the low-rate things (nav, tab list, cursor).
 *
 * Decoding is async, so frames can finish out of order. Each is stamped with a
 * sequence number and a late one is dropped rather than drawn over a newer one.
 */
export default function createFrameBus() {
    const listeners = new Set();
    let latest = null; // { bitmap, meta, tabId, seq }
    let seq = 0;

    return {
        /** Sequence number to stamp the next decode with. */
        nextSeq() {
            seq += 1;
            return seq;
        },

        /** Publish a decoded frame, unless a newer one already landed. */
        push(frame) {
            if (latest && frame.seq < latest.seq) {
                frame.bitmap?.close?.();
                return;
            }
            const prev = latest;
            latest = frame;
            if (prev && prev.bitmap !== frame.bitmap) prev.bitmap?.close?.();
            listeners.forEach((fn) => fn(frame));
        },

        /** The most recent frame, for a subscriber that mounts mid-stream. */
        get current() {
            return latest;
        },

        subscribe(fn) {
            listeners.add(fn);
            return () => listeners.delete(fn);
        },

        /** Drop everything: called when the socket closes. */
        reset() {
            latest?.bitmap?.close?.();
            latest = null;
        },
    };
}
