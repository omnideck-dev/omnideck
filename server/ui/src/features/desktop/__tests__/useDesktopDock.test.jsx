import { act, renderHook } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import useDesktopDock from '../useDesktopDock.jsx';

const APP = { slug: 'text-lab', title: 'Text Lab', icon: 'bi-fonts' };
const FILE_TAB = { id: 'file:/tmp/note.txt', label: 'note.txt' };

function makePreview() {
    return {
        tabs: [FILE_TAB],
        activeTab: FILE_TAB.id,
        setActiveTab: vi.fn(),
    };
}

describe('useDesktopDock', () => {
    it('combines Custom App and workspace preview contributions', () => {
        const preview = makePreview();
        const { result } = renderHook(() => useDesktopDock({ customApp: APP, preview }));

        expect(result.current.items.map((item) => item.id)).toEqual([
            'custom-app:text-lab',
            'file:/tmp/note.txt',
        ]);

        act(() => result.current.showCustomApp());
        expect(result.current.activeItemId).toBe('custom-app:text-lab');

        act(() => result.current.selectItem(FILE_TAB.id));
        expect(result.current.activeItemId).toBe(FILE_TAB.id);
        expect(preview.setActiveTab).toHaveBeenCalledWith(FILE_TAB.id);
    });

    it('keeps dock width outside workspace state', () => {
        const { result } = renderHook(() => useDesktopDock({
            customApp: null,
            preview: makePreview(),
        }));
        act(() => result.current.setSplitPosition(55));
        expect(result.current.splitPosition).toBe(55);
    });
});
