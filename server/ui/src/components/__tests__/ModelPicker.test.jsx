import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';

import ModelPicker, { invalidateModelCache } from '../ModelPicker.jsx';

beforeEach(() => {
    invalidateModelCache();
});

afterEach(() => {
    vi.restoreAllMocks();
});

test('manually refreshes models pulled outside the application', async () => {
    let models = [{ name: 'llama3.2:latest' }];
    globalThis.fetch = vi.fn(() => Promise.resolve({
        ok: true,
        status: 200,
        json: async () => ({ models }),
    }));

    render(
        <ModelPicker
            providers={[{ name: 'ollama', label: 'Ollama' }]}
            selectedProvider="ollama"
            selectedModel=""
            onSelect={vi.fn()}
            defaultOpen
        />,
    );

    expect(await screen.findByText('llama3.2:latest')).toBeInTheDocument();

    models = [
        { name: 'llama3.2:latest' },
        { name: 'deepseek-r1:cloud' },
    ];
    fireEvent.click(screen.getByTestId('model-picker-refresh'));

    expect(await screen.findByText('deepseek-r1:cloud')).toBeInTheDocument();
    await waitFor(() => expect(globalThis.fetch).toHaveBeenCalledTimes(2));
});

test('refreshes every open picker displaying the same provider', async () => {
    let models = [{ name: 'qwen3:latest' }];
    globalThis.fetch = vi.fn(() => Promise.resolve({
        ok: true,
        status: 200,
        json: async () => ({ models }),
    }));

    render(
        <>
            <ModelPicker providers={[{ name: 'ollama' }]} defaultOpen />
            <ModelPicker providers={[{ name: 'ollama' }]} defaultOpen />
        </>,
    );

    await waitFor(() => expect(screen.getAllByText('qwen3:latest')).toHaveLength(2));

    models = [{ name: 'qwen3:latest' }, { name: 'qwen3-coder:cloud' }];
    fireEvent.click(screen.getAllByTestId('model-picker-refresh')[0]);

    await waitFor(() => expect(screen.getAllByText('qwen3-coder:cloud')).toHaveLength(2));
    expect(globalThis.fetch).toHaveBeenCalledTimes(2);
});
