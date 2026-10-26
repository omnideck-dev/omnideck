import { act, renderHook } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import useConversationActivity from '../useConversationActivity.js';

let source;
function renderActivity() {
    vi.stubGlobal('EventSource', class {
        constructor(url) {
            this.url = url;
            this.close = vi.fn();
            source = this;
        }
    });
    return renderHook(() => useConversationActivity());
}
const run = (conversation_id, run_id = conversation_id) => ({ conversation_id, run_id });
function emit(type, runs) {
    act(() => source.onmessage({ data: JSON.stringify({ type, runs }) }));
}
afterEach(() => vi.unstubAllGlobals());

describe('conversation activity', () => {
    it('discovers active runs, marks only background finishes, and clears on opening', () => {
        const { result, unmount } = renderActivity();
        act(() => result.current.setVisibleConversation('one'));
        emit('snapshot', [run('one'), run('two')]);
        expect(result.current.activity.running.size).toBe(2);
        expect(result.current.activity.finished.size).toBe(0);
        emit('finished', [run('one'), run('two')]);
        expect([...result.current.activity.finished]).toEqual(['two']);
        act(() => result.current.setVisibleConversation('two'));
        expect(result.current.activity.finished.size).toBe(0);
        expect(source.url).toBe('/api/chat/activity');
        unmount();
        expect(source.close).toHaveBeenCalledOnce();
    });

    it('reconciles missed completion on reconnect without restoring historical dots', () => {
        const { result, unmount } = renderActivity();
        emit('snapshot', [run('one'), run('two')]);
        emit('snapshot', [run('two'), run('three')]);
        expect([...result.current.activity.finished]).toEqual(['one']);
        expect([...result.current.activity.running.keys()]).toEqual(['two', 'three']);
        unmount();
        const fresh = renderActivity();
        emit('snapshot', [run('three')]);
        expect(fresh.result.current.activity.finished.size).toBe(0);
    });

    it('does not let completion of an older run clear a newer run', () => {
        const { result } = renderActivity();
        emit('snapshot', [run('one', 'old')]);
        emit('started', [run('one', 'new')]);
        emit('finished', [run('one', 'old')]);
        expect(result.current.activity.running.get('one')).toBe('new');
        expect(result.current.activity.finished.size).toBe(0);
        emit('finished', [run('one', 'new')]);
        expect(result.current.activity.finished.has('one')).toBe(true);
        emit('started', [run('one', 'next')]);
        expect(result.current.activity.finished.size).toBe(0);
    });
    it('marks a selected but hidden conversation finished and clears when visible again', () => {
        const { result } = renderActivity();
        act(() => result.current.setVisibleConversation('one'));
        emit('snapshot', [run('one')]);
        act(() => result.current.setVisibleConversation(null));
        emit('finished', [run('one')]);
        expect(result.current.activity.finished.has('one')).toBe(true);
        act(() => result.current.setVisibleConversation('one'));
        expect(result.current.activity.finished.size).toBe(0);
    });

    it('rejects an entire malformed message and keeps processing subsequent messages', () => {
        const report = vi.spyOn(console, 'error').mockImplementation(() => {});
        const { result } = renderActivity();
        emit('snapshot', [run('one')]);
        emit('finished', [run('one'), { conversation_id: 'two' }]);
        expect(result.current.activity.running.has('one')).toBe(true);
        expect(result.current.activity.finished.size).toBe(0);
        emit('finished', [run('one')]);
        expect(result.current.activity.finished.has('one')).toBe(true);
        expect(report).toHaveBeenCalledOnce();
        report.mockRestore();
    });

});
