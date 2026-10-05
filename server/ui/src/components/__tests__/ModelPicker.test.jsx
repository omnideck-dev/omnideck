import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';

import ModelPicker, { invalidateModelCache } from '../ModelPicker.jsx';

beforeEach(() => {
    invalidateModelCache();
});

afterEach(() => {
    vi.restoreAllMocks();
});

function mockProviderModels() {
    globalThis.fetch = vi.fn(async (url) => ({
        ok: true,
        json: async () => ({ models: [{ name: `${new URL(url, 'http://localhost').searchParams.get('provider')}-model` }] }),
    }));
}

test('a saved removed provider falls back for browsing without changing the selection', async () => {
    mockProviderModels();
    const onSelect = vi.fn();
    render(<ModelPicker providers={[{ name: 'openrouter' }]} selectedProvider="ollama"
        selectedModel="old-model" onSelect={onSelect} />);
    fireEvent.click(screen.getByTestId('model-picker-trigger'));
    expect(await screen.findByText('openrouter-model')).toBeInTheDocument();
    expect(fetch).toHaveBeenCalledWith('/api/models?provider=openrouter');
    expect(onSelect).not.toHaveBeenCalled();
    expect(screen.getByTestId('model-picker-trigger')).toHaveAttribute('data-selected-provider', 'ollama');
    fireEvent.keyDown(document, { key: 'Escape' });
    fireEvent.click(screen.getByTestId('model-picker-trigger'));
    fireEvent.click(await screen.findByText('openrouter-model'));
    expect(onSelect).toHaveBeenCalledWith('openrouter', 'openrouter-model', { name: 'openrouter-model' });
});

test('removing the browsed provider while open switches to the remaining provider', async () => {
    mockProviderModels();
    const onSelect = vi.fn();
    const { rerender } = render(<ModelPicker providers={[{ name: 'ollama' }, { name: 'openrouter' }]}
        selectedProvider="ollama" onSelect={onSelect} defaultOpen />);
    expect(await screen.findByText('ollama-model')).toBeInTheDocument();
    fireEvent.change(screen.getByPlaceholderText('Search ollama models…'), { target: { value: 'ollama' } });
    rerender(<ModelPicker providers={[{ name: 'openrouter' }]} selectedProvider="ollama" onSelect={onSelect} defaultOpen />);
    expect(await screen.findByText('openrouter-model')).toBeInTheDocument();
    expect(screen.queryByText('ollama-model')).not.toBeInTheDocument();
    expect(screen.getByPlaceholderText('Search openrouter models…')).toHaveValue('');
    expect(onSelect).not.toHaveBeenCalled();
});

test('an empty catalog disables the picker and recovers when a provider is added', async () => {
    mockProviderModels();
    const { rerender } = render(<ModelPicker providers={[]} selectedProvider="ollama" defaultOpen />);
    expect(screen.getByTestId('model-picker-trigger')).toBeDisabled();
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument();
    expect(fetch).not.toHaveBeenCalled();
    rerender(<ModelPicker providers={[{ name: 'openrouter' }]} selectedProvider="ollama" defaultOpen />);
    expect(await screen.findByText('openrouter-model')).toBeInTheDocument();
    rerender(<ModelPicker providers={[]} selectedProvider="ollama" defaultOpen />);
    expect(screen.getByTestId('model-picker-trigger')).toBeDisabled();
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument();
});

test('late model results from a removed provider do not replace the current list', async () => {
    let finishOld;
    globalThis.fetch = vi.fn((url) => url.endsWith('ollama')
        ? new Promise((resolve) => { finishOld = resolve; })
        : Promise.resolve({ ok: true, json: async () => ({ models: [{ name: 'current-model' }] }) }));
    const { rerender } = render(<ModelPicker providers={[{ name: 'ollama' }, { name: 'openrouter' }]}
        selectedProvider="ollama" defaultOpen />);
    rerender(<ModelPicker providers={[{ name: 'openrouter' }]} selectedProvider="ollama" defaultOpen />);
    expect(await screen.findByText('current-model')).toBeInTheDocument();
    await act(async () => { finishOld({ ok: true, json: async () => ({ models: [{ name: 'stale-model' }] }) }); });
    expect(screen.queryByText('stale-model')).not.toBeInTheDocument();
    expect(screen.getByText('current-model')).toBeInTheDocument();
});

test('keeps a configured saved provider even when it is not first', async () => {
    mockProviderModels();
    render(<ModelPicker providers={[{ name: 'ollama' }, { name: 'openrouter' }]}
        selectedProvider="openrouter" defaultOpen />);
    expect(await screen.findByText('openrouter-model')).toBeInTheDocument();
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(fetch).toHaveBeenCalledWith('/api/models?provider=openrouter');
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
