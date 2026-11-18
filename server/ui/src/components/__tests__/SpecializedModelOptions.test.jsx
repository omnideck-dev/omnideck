import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import SpecializedModelOptions, { ModelDefaultsSummary } from '../SpecializedModelOptions.jsx';

const CAPABILITIES = {
    detected: true,
    apiLabel: 'Responses',
    contextWindow: 1_050_000,
    maxOutputTokens: 128_000,
};

describe('ModelDefaultsSummary', () => {
    it('shows the automatic role cap when no output override exists', () => {
        render(<ModelDefaultsSummary capabilities={CAPABILITIES} role="vision" outputCap={512} />);

        expect(screen.getByTestId('vision-model-detection')).toHaveTextContent(
            'Auto sampling · 512-token role cap',
        );
    });

    it('shows an explicit output override instead of claiming the automatic cap', () => {
        render(
            <ModelDefaultsSummary
                capabilities={CAPABILITIES}
                role="vision"
                outputCap={512}
                options={{ temperature: 0.2, num_predict: 128 }}
            />,
        );

        expect(screen.getByTestId('vision-model-detection')).toHaveTextContent(
            'Custom sampling · 128 output override',
        );
        expect(screen.getByTestId('vision-model-detection')).not.toHaveTextContent(
            '512-token role cap',
        );
    });
});

describe('SpecializedModelOptions thinking controls', () => {
    it('shows Ollama GPT-OSS thinking levels', async () => {
        const user = userEvent.setup();
        render(
            <SpecializedModelOptions
                role="vision"
                capabilities={{
                    ...CAPABILITIES,
                    api: 'ollama',
                    controls: ['think'],
                    thinkingControl: 'reasoning_effort',
                    thinkingLevels: ['low', 'medium', 'high'],
                    thinkingRequired: true,
                }}
                options={{}}
                open
                onToggle={() => {}}
                onPatch={() => {}}
            />,
        );

        expect(screen.getByTestId('vision-thinking-level')).toBeInTheDocument();
        await user.click(screen.getByRole('combobox', { name: 'Vision thinking level' }));
        expect(screen.getByRole('option', { name: 'Automatic' })).toBeInTheDocument();
        expect(screen.getByRole('option', { name: 'High' })).toBeInTheDocument();
    });

    it.each([
        ['can be turned off', false, 'Off', 'Automatic'],
        ['always think', true, 'Automatic', 'Off'],
    ])('offers the honest idle choice for Claude models that %s', async (
        _label, thinkingRequired, shown, hidden,
    ) => {
        const user = userEvent.setup();
        render(
            <SpecializedModelOptions
                role="vision"
                capabilities={{
                    ...CAPABILITIES,
                    api: 'anthropic_messages',
                    controls: ['think', 'reasoning_effort'],
                    thinkingControl: 'reasoning_effort',
                    thinkingLevels: ['low', 'medium', 'high', 'xhigh', 'max'],
                    thinkingDefault: 'medium',
                    thinkingRequired,
                }}
                options={{}}
                open
                onToggle={() => {}}
                onPatch={() => {}}
            />,
        );

        await user.click(screen.getByRole('combobox', { name: 'Vision thinking level' }));
        expect(screen.getByRole('option', { name: shown })).toBeInTheDocument();
        expect(screen.queryByRole('option', { name: hidden })).not.toBeInTheDocument();
    });

    it('hides fields thinking turns off and clears a refused pair', async () => {
        const user = userEvent.setup();
        const onPatch = vi.fn();
        const capabilities = {
            ...CAPABILITIES,
            api: 'anthropic_messages',
            controls: ['temperature', 'top_p', 'top_k', 'think', 'thinking_budget', 'num_predict'],
            thinkingControl: 'thinking_budget',
            thinkingLevels: ['minimal', 'standard', 'extended'],
            thinkingRequired: false,
            thinkingExcludedControls: ['temperature', 'top_k'],
            exclusiveControls: [['temperature', 'top_p']],
        };
        const { rerender } = render(
            <SpecializedModelOptions
                role="vision"
                capabilities={capabilities}
                options={{ temperature: 0.4 }}
                think={false}
                open
                onToggle={() => {}}
                onPatch={onPatch}
            />,
        );

        await user.type(screen.getByTestId('vision-option-top_p'), '9');
        expect(onPatch).toHaveBeenLastCalledWith({
            vision_options: { temperature: null, top_p: 9 },
        });

        rerender(
            <SpecializedModelOptions
                role="vision"
                capabilities={capabilities}
                options={{}}
                think
                open
                onToggle={() => {}}
                onPatch={onPatch}
            />,
        );
        expect(screen.queryByTestId('vision-option-temperature')).not.toBeInTheDocument();
        expect(screen.queryByTestId('vision-option-top_k')).not.toBeInTheDocument();
        expect(screen.getByTestId('vision-option-top_p')).toBeInTheDocument();
    });
});
