import { render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';

import FolderAppHost from '../FolderAppHost.jsx';

const SAMPLE = { slug: 'text-lab', title: 'Text Lab' };

beforeEach(() => {
    global.fetch = vi.fn(() => Promise.resolve({
        ok: true,
        json: async () => ({ ok: true, result: { words: 3 } }),
    }));
});

afterEach(() => vi.restoreAllMocks());

test('forwards frame invocation messages to the selected app endpoint', async () => {
    render(<FolderAppHost app={SAMPLE} />);
    const frame = screen.getByTestId('folder-app-frame');
    const postMessage = vi.spyOn(frame.contentWindow, 'postMessage');

    window.dispatchEvent(new MessageEvent('message', {
        source: frame.contentWindow,
        data: { type: 'omnideck:invoke', id: 'request-1', action: 'analyze', args: { text: 'one two three' } },
    }));

    await waitFor(() => expect(global.fetch).toHaveBeenCalledWith(
        '/api/folder-apps/text-lab/invoke/analyze',
        expect.objectContaining({ method: 'POST' }),
    ));
    await waitFor(() => expect(postMessage).toHaveBeenCalledWith({
        type: 'omnideck:result',
        id: 'request-1',
        ok: true,
        result: { words: 3 },
        error: undefined,
    }, '*'));
});

test('allows an app to open chat or seed the composer without sending', () => {
    const onOpenChat = vi.fn();
    const onComposeChat = vi.fn();
    render(<FolderAppHost app={SAMPLE} onOpenChat={onOpenChat} onComposeChat={onComposeChat} />);
    const frame = screen.getByTestId('folder-app-frame');

    window.dispatchEvent(new MessageEvent('message', {
        source: frame.contentWindow,
        data: { type: 'omnideck:chat-open' },
    }));
    window.dispatchEvent(new MessageEvent('message', {
        source: frame.contentWindow,
        data: { type: 'omnideck:chat-compose', text: 'Review this', context: { text: 'Draft' } },
    }));

    expect(onOpenChat).toHaveBeenCalledOnce();
    expect(onComposeChat).toHaveBeenCalledWith({ text: 'Review this', context: { text: 'Draft' } });
    expect(global.fetch).not.toHaveBeenCalled();
});
