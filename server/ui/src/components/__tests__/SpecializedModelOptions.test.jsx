import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';

import SpecializedModelOptions, { ModelDefaultsSummary } from '../SpecializedModelOptions.jsx';

const CAPABILITIES = {
    detected: true,
    upstreamProvider: 'Amazon Bedrock',
    apiLabel: 'Responses',
    contextWindow: 1_050_000,
    maxOutputTokens: 128_000,
};

describe('ModelDefaultsSummary', () => {
    it('shows the automatic role cap when no output override exists', () => {
        render(<ModelDefaultsSummary capabilities={CAPABILITIES} role="vision" />);

        expect(screen.getByTestId('vision-model-detection')).toHaveTextContent(
            'Auto sampling · 512-token role cap',
        );
    });

    it('shows an explicit output override instead of claiming the automatic cap', () => {
        render(
            <ModelDefaultsSummary
                capabilities={CAPABILITIES}
                role="vision"
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
    it('shows Ollama GPT-OSS levels instead of a boolean toggle', async () => {
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
        expect(screen.queryByTestId('vision-think-toggle')).not.toBeInTheDocument();
        await user.click(screen.getByRole('combobox', { name: 'Vision thinking level' }));
        expect(screen.getByRole('option', { name: 'Automatic' })).toBeInTheDocument();
        expect(screen.getByRole('option', { name: 'High' })).toBeInTheDocument();
    });

    it('keeps the toggle for boolean-only Ollama thinking models', () => {
        render(
            <SpecializedModelOptions
                role="vision"
                capabilities={{
                    ...CAPABILITIES,
                    api: 'ollama',
                    controls: ['think'],
                    thinkingControl: 'toggle',
                    thinkingLevels: [],
                    thinkingRequired: false,
                }}
                options={{}}
                open
                onToggle={() => {}}
                onPatch={() => {}}
            />,
        );

        expect(screen.getByTestId('vision-think-toggle')).toBeInTheDocument();
        expect(screen.queryByTestId('vision-thinking-level')).not.toBeInTheDocument();
    });
});
