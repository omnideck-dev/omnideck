import { render, act } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import useStreamStall from '../useStreamStall.js';

// Captures the hook's latest return so assertions can read it between acts.
let latest;
function Harness({ activityKey, active, opts }) {
    latest = useStreamStall(activityKey, active, opts);
    return null;
}

const OPTS = { delayMs: 1000, checkMs: 400 };

beforeEach(() => {
    vi.useFakeTimers();
});

afterEach(() => {
    vi.useRealTimers();
    latest = undefined;
});

describe('useStreamStall', () => {
    it('reports a stall after the delay elapses with no new output', () => {
        render(<Harness activityKey="0:0" active opts={OPTS} />);
        expect(latest).toBe(false);
        act(() => { vi.advanceTimersByTime(1200); });
        expect(latest).toBe(true);
    });

    it('does not stall while output keeps advancing', () => {
        const { rerender } = render(<Harness activityKey="0:0" active opts={OPTS} />);
        // New output arrives just before each stall would fire.
        for (let i = 1; i <= 4; i += 1) {
            act(() => { vi.advanceTimersByTime(800); });
            rerender(<Harness activityKey={`0:${i * 10}`} active opts={OPTS} />);
        }
        expect(latest).toBe(false);
    });

    it('clears a stall once new output arrives', () => {
        const { rerender } = render(<Harness activityKey="0:0" active opts={OPTS} />);
        act(() => { vi.advanceTimersByTime(1200); });
        expect(latest).toBe(true);
        rerender(<Harness activityKey="1:5" active opts={OPTS} />);
        expect(latest).toBe(false);
    });

    it('never stalls when inactive', () => {
        render(<Harness activityKey="0:0" active={false} opts={OPTS} />);
        act(() => { vi.advanceTimersByTime(5000); });
        expect(latest).toBe(false);
    });

    it('does not fire an immediate stall when streaming resumes', () => {
        const { rerender } = render(<Harness activityKey="0:0" active={false} opts={OPTS} />);
        // Time passes while idle, then a new turn starts streaming.
        act(() => { vi.advanceTimersByTime(5000); });
        rerender(<Harness activityKey="0:0" active opts={OPTS} />);
        act(() => { vi.advanceTimersByTime(500); });
        expect(latest).toBe(false);
        act(() => { vi.advanceTimersByTime(700); });
        expect(latest).toBe(true);
    });
});
