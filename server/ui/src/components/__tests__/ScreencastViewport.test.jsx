import { act, render } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import ScreencastViewport from '../ScreencastViewport.jsx';
import createFrameBus from '../../features/browser/frameBus.js';

// Animation frames are driven by hand so the batched paint and the batched input
// flush both happen at a point the test chooses.
let frameCallbacks = [];
const flushFrames = () => {
    const due = frameCallbacks;
    frameCallbacks = [];
    due.forEach((fn) => fn(performance.now()));
};

/**
 * Render an engaged viewport whose canvas is displayed at `displayed` size while
 * the frame it holds is `capture` pixels, standing for a page of `page` CSS px.
 */
function setup({ capture, page, displayed }) {
    const bus = createFrameBus();
    const sendInput = vi.fn();
    const view = render(
        <ScreencastViewport
            frameBus={bus}
            engaged
            active
            sendInput={sendInput}
            className="viewport"
            imgClassName="frame"
        />,
    );
    const canvas = view.getByTestId('browser-frame');
    canvas.getBoundingClientRect = () => ({
        left: 0, top: 0, width: displayed.width, height: displayed.height,
        right: displayed.width, bottom: displayed.height, x: 0, y: 0,
    });
    act(() => {
        bus.push({
            bitmap: { width: capture.width, height: capture.height, close: vi.fn() },
            meta: {
                deviceWidth: page.width,
                deviceHeight: page.height,
                pageScale: page.scale ?? 1,
                offsetTop: page.offsetTop ?? 0,
            },
            tabId: 1,
            seq: bus.nextSeq(),
        });
        flushFrames();
    });
    return { surface: view.getByTestId('browser-viewport'), sendInput, view, bus };
}

const mouse = (type, init) => new MouseEvent(type, { bubbles: true, ...init });

function pasteEvent(text) {
    const event = new Event('paste', { bubbles: true, cancelable: true });
    Object.defineProperty(event, 'clipboardData', {
        value: { getData: (type) => type === 'text/plain' ? text : '' },
    });
    return event;
}

describe('ScreencastViewport', () => {
    beforeEach(() => {
        frameCallbacks = [];
        vi.stubGlobal('requestAnimationFrame', (fn) => {
            frameCallbacks.push(fn);
            return frameCallbacks.length;
        });
        vi.stubGlobal('cancelAnimationFrame', () => {});
        // jsdom has no 2d context; the drawing itself is not what is under test.
        HTMLCanvasElement.prototype.getContext = () => ({ drawImage: vi.fn() });
    });

    afterEach(() => {
        vi.unstubAllGlobals();
    });

    it('maps a click through the frame metadata, not the image size', () => {
        // Capture is scaled to half the page's CSS size. Deriving coordinates
        // from the image's own pixels would land every click at half position.
        const { surface, sendInput } = setup({
            capture: { width: 720, height: 450 },
            page: { width: 1440, height: 900 },
            displayed: { width: 360, height: 225 },
        });

        act(() => {
            surface.dispatchEvent(mouse('pointerdown', { clientX: 180, clientY: 112.5, button: 0, buttons: 1 }));
        });

        const press = sendInput.mock.calls.map(([m]) => m).find((m) => m.type === 'mousedown');
        // Halfway across a 360px-wide view is halfway across a 1440px page.
        expect(press.x).toBe(720);
        expect(press.y).toBe(450);
    });

    it('maps a click at the origin to the page origin', () => {
        const { surface, sendInput } = setup({
            capture: { width: 720, height: 450 },
            page: { width: 1440, height: 900 },
            displayed: { width: 360, height: 225 },
        });

        act(() => {
            surface.dispatchEvent(mouse('pointerdown', { clientX: 0, clientY: 0, button: 0, buttons: 1 }));
        });

        const press = sendInput.mock.calls.map(([m]) => m).find((m) => m.type === 'mousedown');
        expect([press.x, press.y]).toEqual([0, 0]);
    });

    it('divides out a page scale factor', () => {
        const { surface, sendInput } = setup({
            capture: { width: 720, height: 450 },
            page: { width: 1440, height: 900, scale: 2 },
            displayed: { width: 720, height: 450 },
        });

        act(() => {
            surface.dispatchEvent(mouse('pointerdown', { clientX: 360, clientY: 0, button: 0, buttons: 1 }));
        });

        const press = sendInput.mock.calls.map(([m]) => m).find((m) => m.type === 'mousedown');
        expect(press.x).toBe(360);
    });

    it('sends the newest pointer sample of a frame, not the first', () => {
        const { surface, sendInput } = setup({
            capture: { width: 1440, height: 900 },
            page: { width: 1440, height: 900 },
            displayed: { width: 1440, height: 900 },
        });

        act(() => {
            surface.dispatchEvent(mouse('pointermove', { clientX: 10, clientY: 10, buttons: 0 }));
            surface.dispatchEvent(mouse('pointermove', { clientX: 20, clientY: 20, buttons: 0 }));
            surface.dispatchEvent(mouse('pointermove', { clientX: 30, clientY: 30, buttons: 0 }));
            flushFrames();
        });

        const moves = sendInput.mock.calls.map(([m]) => m).filter((m) => m.type === 'mousemove');
        expect(moves).toHaveLength(1);
        expect([moves[0].x, moves[0].y]).toEqual([30, 30]);
    });

    it('sums wheel deltas into one message per frame', () => {
        // A trackpad emits far more wheel events than the channel should carry,
        // but collapsing them must still scroll the same distance.
        const { surface, sendInput } = setup({
            capture: { width: 1440, height: 900 },
            page: { width: 1440, height: 900 },
            displayed: { width: 1440, height: 900 },
        });

        act(() => {
            surface.dispatchEvent(new WheelEvent('wheel', { bubbles: true, deltaX: 0, deltaY: 12, clientX: 5, clientY: 5 }));
            surface.dispatchEvent(new WheelEvent('wheel', { bubbles: true, deltaX: 3, deltaY: 20, clientX: 5, clientY: 5 }));
            flushFrames();
        });

        const wheels = sendInput.mock.calls.map(([m]) => m).filter((m) => m.type === 'wheel');
        expect(wheels).toHaveLength(1);
        expect([wheels[0].dx, wheels[0].dy]).toEqual([3, 32]);
    });

    it('flushes a pending move before a press, so the click lands where the pointer is', () => {
        const { surface, sendInput } = setup({
            capture: { width: 1440, height: 900 },
            page: { width: 1440, height: 900 },
            displayed: { width: 1440, height: 900 },
        });

        act(() => {
            surface.dispatchEvent(mouse('pointermove', { clientX: 400, clientY: 300, buttons: 0 }));
            surface.dispatchEvent(mouse('pointerdown', { clientX: 400, clientY: 300, button: 0, buttons: 1 }));
        });

        const types = sendInput.mock.calls.map(([m]) => m.type);
        expect(types).toEqual(['mousemove', 'mousedown']);
    });

    it('sends one message per keystroke, with the text left to the server', () => {
        const { surface, sendInput } = setup({
            capture: { width: 100, height: 100 },
            page: { width: 100, height: 100 },
            displayed: { width: 100, height: 100 },
        });

        const keydown = new KeyboardEvent('keydown', {
            bubbles: true, cancelable: true, key: 'a', code: 'KeyA',
        });
        act(() => {
            surface.dispatchEvent(keydown);
        });

        expect(keydown.defaultPrevented).toBe(true);
        const sent = sendInput.mock.calls.map(([m]) => m);
        expect(sent).toHaveLength(1);
        expect(sent[0]).toMatchObject({ type: 'keydown', key: 'a', code: 'KeyA' });
        expect(sent.some((m) => m.type === 'text')).toBe(false);
    });

    it.each([
        ['Ctrl+V', { key: 'v', code: 'KeyV', ctrlKey: true }],
        ['Cmd+V', { key: 'v', code: 'KeyV', metaKey: true }],
        ['Ctrl+Shift+V', { key: 'V', code: 'KeyV', ctrlKey: true, shiftKey: true }],
        ['Cmd+Shift+V', { key: 'V', code: 'KeyV', metaKey: true, shiftKey: true }],
        ['Shift+Insert', { key: 'Insert', code: 'Insert', shiftKey: true }],
    ])('allows native %s paste and forwards its text exactly once', (_shortcut, keys) => {
        const { surface, sendInput, view } = setup({
            capture: { width: 100, height: 100 },
            page: { width: 100, height: 100 },
            displayed: { width: 100, height: 100 },
        });
        const outerKeydown = vi.fn();
        const outerPaste = vi.fn();
        view.container.addEventListener('keydown', outerKeydown);
        view.container.addEventListener('paste', outerPaste);
        const keydown = new KeyboardEvent('keydown', { bubbles: true, cancelable: true, ...keys });
        let nativePasteAllowed;
        act(() => {
            nativePasteAllowed = surface.dispatchEvent(keydown);
        });

        // Cancelling this keydown prevents the browser from producing a paste
        // event. Testing only a dispatched paste event misses that failure.
        expect(nativePasteAllowed).toBe(true);
        expect(keydown.defaultPrevented).toBe(false);
        expect(outerKeydown).not.toHaveBeenCalled();
        expect(sendInput).not.toHaveBeenCalled();

        // jsdom has no native clipboard action; supply the subsequent event
        // only after verifying the shortcut allows that action to occur.
        const text = 'First line\nSecond line — café';
        const paste = pasteEvent(text);
        act(() => {
            surface.dispatchEvent(paste);
        });
        expect(paste.defaultPrevented).toBe(true);
        expect(outerPaste).not.toHaveBeenCalled();
        expect(sendInput.mock.calls).toEqual([[{ type: 'paste', text }]]);
        expect(surface).not.toHaveTextContent(text);
    });

    it('does not forward an empty text paste', () => {
        const { surface, sendInput } = setup({
            capture: { width: 100, height: 100 },
            page: { width: 100, height: 100 },
            displayed: { width: 100, height: 100 },
        });
        const paste = pasteEvent('');
        act(() => {
            surface.dispatchEvent(paste);
        });
        expect(paste.defaultPrevented).toBe(true);
        expect(sendInput).not.toHaveBeenCalled();
    });

    it.each([
        ['not engaged', { engaged: false, active: true }],
        ['not selected', { engaged: true, active: false }],
    ])('leaves clipboard events alone while %s', (_condition, state) => {
        const sendInput = vi.fn();
        const view = render(<ScreencastViewport frameBus={createFrameBus()} sendInput={sendInput} {...state} />);
        const surface = view.getByTestId('browser-viewport');
        const outerPaste = vi.fn();
        view.container.addEventListener('paste', outerPaste);
        const keydown = new KeyboardEvent('keydown', {
            bubbles: true, cancelable: true, key: 'v', code: 'KeyV', ctrlKey: true,
        });
        const paste = pasteEvent('Keep this local');
        act(() => {
            surface.dispatchEvent(keydown);
            surface.dispatchEvent(paste);
        });
        expect(keydown.defaultPrevented).toBe(false);
        expect(paste.defaultPrevented).toBe(false);
        expect(outerPaste).toHaveBeenCalledOnce();
        expect(sendInput).not.toHaveBeenCalled();
    });

    it('applies the mirrored remote cursor while engaged', () => {
        const bus = createFrameBus();
        const { getByTestId } = render(
            <ScreencastViewport frameBus={bus} engaged active sendInput={vi.fn()} cursor="pointer" />,
        );
        expect(getByTestId('browser-viewport').style.cursor).toBe('pointer');
    });

    it('keeps one frame element, hidden only until something is drawn', () => {
        // Callers wait on this element, so it must never be swapped for another.
        const bus = createFrameBus();
        const { getByTestId } = render(
            <ScreencastViewport frameBus={bus} sendInput={vi.fn()} />,
        );
        const el = getByTestId('browser-frame');
        expect(el.tagName).toBe('CANVAS');
        expect(el.hidden).toBe(true);

        act(() => {
            bus.push({
                bitmap: { width: 10, height: 10, close: vi.fn() },
                meta: { deviceWidth: 10, deviceHeight: 10, pageScale: 1, offsetTop: 0 },
                tabId: 1,
                seq: bus.nextSeq(),
            });
            flushFrames();
        });

        expect(getByTestId('browser-frame')).toBe(el);
        expect(el.hidden).toBe(false);
    });

    it('forwards no pointer input before a live frame establishes the coordinate space', () => {
        // The canvas may be showing the agent's screenshot, whose pixels are not
        // page pixels. Dropping the click beats landing it somewhere else.
        const bus = createFrameBus();
        const sendInput = vi.fn();
        const { getByTestId } = render(
            <ScreencastViewport
                frameBus={bus}
                fallbackSrc="data:image/png;base64,AAA"
                engaged
                active
                sendInput={sendInput}
            />,
        );
        const surface = getByTestId('browser-viewport');

        act(() => {
            surface.dispatchEvent(mouse('pointerdown', { clientX: 5, clientY: 5, button: 0, buttons: 1 }));
            surface.dispatchEvent(mouse('pointermove', { clientX: 6, clientY: 6, buttons: 0 }));
            surface.dispatchEvent(new WheelEvent('wheel', { bubbles: true, deltaY: 10, clientX: 5, clientY: 5 }));
            flushFrames();
        });
        expect(sendInput).not.toHaveBeenCalled();

        // Keystrokes carry no coordinates, so they are never withheld.
        act(() => {
            surface.dispatchEvent(new KeyboardEvent('keydown', { bubbles: true, key: 'a', code: 'KeyA' }));
        });
        expect(sendInput.mock.calls.map(([m]) => m.type)).toEqual(['keydown']);
    });

    it('starts forwarding pointer input once a live frame has landed', () => {
        const { surface, sendInput } = setup({
            capture: { width: 100, height: 100 },
            page: { width: 100, height: 100 },
            displayed: { width: 100, height: 100 },
        });
        act(() => {
            surface.dispatchEvent(mouse('pointerdown', { clientX: 10, clientY: 10, button: 0, buttons: 1 }));
        });
        expect(sendInput.mock.calls.some(([m]) => m.type === 'mousedown')).toBe(true);
    });

    it('forwards no input while control is not engaged', () => {
        const bus = createFrameBus();
        const sendInput = vi.fn();
        const { getByTestId } = render(
            <ScreencastViewport frameBus={bus} engaged={false} sendInput={sendInput} />,
        );
        getByTestId('browser-viewport').dispatchEvent(
            mouse('pointerdown', { clientX: 1, clientY: 1, button: 0, buttons: 1 }),
        );
        expect(sendInput).not.toHaveBeenCalled();
    });
});
