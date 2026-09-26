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

test('shows friendly Aperture model names while selecting the qualified id', async () => {
    const onSelect = vi.fn();
    globalThis.fetch = vi.fn(() => Promise.resolve({
        ok: true,
        status: 200,
        json: async () => ({
            models: [{
                name: 'bedrock/us.anthropic.claude-sonnet-4-6',
                display_name: 'us.anthropic.claude-sonnet-4-6',
                upstream_provider: 'Amazon Bedrock',
                wire_api: 'Amazon Bedrock',
            }],
        }),
    }));

    render(
        <ModelPicker
            providers={[{ name: 'aperture', label: 'Tailscale Aperture' }]}
            selectedProvider="aperture"
            selectedModel=""
            onSelect={onSelect}
            defaultOpen
        />,
    );

    fireEvent.click(await screen.findByText('us.anthropic.claude-sonnet-4-6'));

    expect(onSelect).toHaveBeenCalledWith(
        'aperture',
        'bedrock/us.anthropic.claude-sonnet-4-6',
        expect.objectContaining({ upstream_provider: 'Amazon Bedrock' }),
    );
});

test('resolves the selected model metadata while the picker is closed', async () => {
    const onModelResolved = vi.fn();
    globalThis.fetch = vi.fn(() => Promise.resolve({
        ok: true,
        status: 200,
        json: async () => ({
            models: [{
                name: 'bedrock/openai.gpt-5.6-luna',
                inference_api: 'openai_responses',
                inference_controls: ['think', 'reasoning_effort'],
            }],
        }),
    }));

    render(
        <ModelPicker
            providers={[{ name: 'aperture' }]}
            selectedProvider="aperture"
            selectedModel="bedrock/openai.gpt-5.6-luna"
            onSelect={vi.fn()}
            onModelResolved={onModelResolved}
        />,
    );

    await waitFor(() => expect(onModelResolved).toHaveBeenCalledWith(
        'aperture',
        'bedrock/openai.gpt-5.6-luna',
        expect.objectContaining({ inference_api: 'openai_responses' }),
    ));
    expect(globalThis.fetch).toHaveBeenCalledTimes(1);
});
