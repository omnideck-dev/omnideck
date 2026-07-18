import { render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';

import CustomAppHost from '../CustomAppHost.jsx';

const SAMPLE = { slug: 'text-lab', title: 'Text Lab' };

beforeEach(() => {
    global.fetch = vi.fn(() => Promise.resolve({
        ok: true,
        json: async () => ({ ok: true, result: { words: 3 } }),
    }));
});

afterEach(() => vi.restoreAllMocks());

test('runs the trusted app iframe without browser sandbox restrictions', () => {
    render(<CustomAppHost app={SAMPLE} />);
    expect(screen.getByTestId('custom-app-frame')).not.toHaveAttribute('sandbox');
});

test('forwards frame invocation messages to the selected app endpoint', async () => {
    render(<CustomAppHost app={SAMPLE} />);
    const frame = screen.getByTestId('custom-app-frame');
    const postMessage = vi.spyOn(frame.contentWindow, 'postMessage');

    window.dispatchEvent(new MessageEvent('message', {
        source: frame.contentWindow,
        origin: window.location.origin,
        data: { type: 'omnideck:invoke', id: 'request-1', action: 'analyze', args: { text: 'one two three' } },
    }));

    await waitFor(() => expect(global.fetch).toHaveBeenCalledWith(
        '/api/custom-apps/text-lab/invoke/analyze',
        expect.objectContaining({ method: 'POST' }),
    ));
    await waitFor(() => expect(postMessage).toHaveBeenCalledWith({
        type: 'omnideck:result',
        id: 'request-1',
        ok: true,
        result: { words: 3 },
        error: undefined,
    }, window.location.origin));
});

test('ignores bridge messages after the frame navigates to another origin', () => {
    const onOpenChat = vi.fn();
    render(<CustomAppHost app={SAMPLE} onOpenChat={onOpenChat} />);
    const frame = screen.getByTestId('custom-app-frame');

    window.dispatchEvent(new MessageEvent('message', {
        source: frame.contentWindow,
        origin: 'https://example.com',
        data: { type: 'omnideck:chat-open' },
    }));

    expect(onOpenChat).not.toHaveBeenCalled();
});

test('allows an app to open chat or seed the composer without sending', () => {
    const onOpenChat = vi.fn();
    const onComposeChat = vi.fn();
    render(<CustomAppHost app={SAMPLE} onOpenChat={onOpenChat} onComposeChat={onComposeChat} />);
    const frame = screen.getByTestId('custom-app-frame');

    window.dispatchEvent(new MessageEvent('message', {
        source: frame.contentWindow,
        origin: window.location.origin,
        data: { type: 'omnideck:chat-open' },
    }));
    window.dispatchEvent(new MessageEvent('message', {
        source: frame.contentWindow,
        origin: window.location.origin,
        data: { type: 'omnideck:chat-compose', text: 'Review this', context: { text: 'Draft' } },
    }));

    expect(onOpenChat).toHaveBeenCalledOnce();
    expect(onComposeChat).toHaveBeenCalledWith({ text: 'Review this', context: { text: 'Draft' } });
    expect(global.fetch).not.toHaveBeenCalled();
});

test('downloads supported URLs and rejects executable URL schemes', () => {
    render(<CustomAppHost app={SAMPLE} />);
    const frame = screen.getByTestId('custom-app-frame');
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});

    window.dispatchEvent(new MessageEvent('message', {
        source: frame.contentWindow,
        origin: window.location.origin,
        data: {
            type: 'omnideck:download',
            url: './generated/image.png',
            filename: 'image.png',
        },
    }));
    expect(click).toHaveBeenCalledOnce();

    window.dispatchEvent(new MessageEvent('message', {
        source: frame.contentWindow,
        origin: window.location.origin,
        data: {
            type: 'omnideck:download',
            url: 'https://example.com/image.png',
            filename: 'image.png',
        },
    }));
    expect(click).toHaveBeenCalledTimes(2);

    window.dispatchEvent(new MessageEvent('message', {
        source: frame.contentWindow,
        origin: window.location.origin,
        data: {
            type: 'omnideck:download',
            url: 'javascript:alert(1)',
            filename: 'image.png',
        },
    }));
    expect(click).toHaveBeenCalledTimes(2);
});
