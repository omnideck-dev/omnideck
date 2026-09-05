import { describe, expect, it, vi } from 'vitest';

import createFrameBus from '../frameBus.js';

/** A stand-in for an ImageBitmap that records being released. */
function fakeBitmap(label) {
    return { label, close: vi.fn() };
}

const frame = (seq, bitmap) => ({ bitmap, meta: {}, tabId: 1, seq });

describe('Browser createFrameBus', () => {
    it('publishes a frame to every subscriber', () => {
        const bus = createFrameBus();
        const a = vi.fn();
        const b = vi.fn();
        bus.subscribe(a);
        bus.subscribe(b);

        const f = frame(bus.nextSeq(), fakeBitmap('one'));
        bus.push(f);

        expect(a).toHaveBeenCalledWith(f);
        expect(b).toHaveBeenCalledWith(f);
    });

    it('drops a frame that decoded late, so a stale image never overwrites a newer one', () => {
        // Decoding is async, so a frame that started earlier can finish later.
        const bus = createFrameBus();
        const seen = vi.fn();
        bus.subscribe(seen);

        const first = bus.nextSeq();
        const second = bus.nextSeq();
        const late = fakeBitmap('late');

        bus.push(frame(second, fakeBitmap('newer')));
        bus.push(frame(first, late));

        expect(seen).toHaveBeenCalledTimes(1);
        expect(bus.current.bitmap.label).toBe('newer');
        // The dropped frame's bitmap is released rather than leaked.
        expect(late.close).toHaveBeenCalled();
    });

    it('releases the previous bitmap when a newer frame replaces it', () => {
        const bus = createFrameBus();
        const old = fakeBitmap('old');
        bus.push(frame(bus.nextSeq(), old));
        bus.push(frame(bus.nextSeq(), fakeBitmap('new')));

        expect(old.close).toHaveBeenCalled();
    });

    it('exposes the latest frame so a viewport mounting mid-stream has something to draw', () => {
        const bus = createFrameBus();
        expect(bus.current).toBeNull();
        bus.push(frame(bus.nextSeq(), fakeBitmap('only')));
        expect(bus.current.bitmap.label).toBe('only');
    });

    it('stops notifying after unsubscribe', () => {
        const bus = createFrameBus();
        const seen = vi.fn();
        const off = bus.subscribe(seen);
        off();
        bus.push(frame(bus.nextSeq(), fakeBitmap('x')));
        expect(seen).not.toHaveBeenCalled();
    });

    it('releases the held bitmap on reset', () => {
        const bus = createFrameBus();
        const held = fakeBitmap('held');
        bus.push(frame(bus.nextSeq(), held));
        bus.reset();
        expect(held.close).toHaveBeenCalled();
        expect(bus.current).toBeNull();
    });
});
