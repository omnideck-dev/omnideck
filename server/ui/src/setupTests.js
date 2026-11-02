import '@testing-library/jest-dom/vitest';

// jsdom does not supply the browser's native EventSource transport.
globalThis.EventSource = class EventSource {
    close() {}
};
