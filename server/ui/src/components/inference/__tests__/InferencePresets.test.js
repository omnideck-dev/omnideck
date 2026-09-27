import { describe, expect, it } from 'vitest';

import { resolvePreset } from '../InferencePresets.jsx';

describe('model-aware inference presets', () => {
    it('does not apply sampling values that GPT Sol does not support', () => {
        const capabilities = {
            provider: 'aperture',
            api: 'openai_responses',
            controls: ['think', 'reasoning_effort', 'reasoning_summary', 'num_predict'],
            thinkingControl: 'reasoning_effort',
            thinkingDefault: 'medium',
        };

        expect(resolvePreset('balanced', capabilities)).toEqual({});
        expect(resolvePreset('creative', capabilities)).toEqual({});
        expect(resolvePreset('precise', capabilities)).toEqual({});
        expect(resolvePreset('code', capabilities)).toEqual({
            think: true,
            reasoning_effort: 'medium',
        });
    });

    it('uses the discovered Anthropic adaptive-thinking default', () => {
        const preset = resolvePreset('code', {
            provider: 'anthropic',
            api: 'anthropic_messages',
            controls: ['temperature', 'think', 'reasoning_effort'],
            thinkingControl: 'reasoning_effort',
            thinkingDefault: 'high',
        });

        expect(preset).toEqual({
            temperature: 1,
            think: true,
            reasoning_effort: 'high',
        });
    });

    it('uses the discovered Ollama thinking level', () => {
        const preset = resolvePreset('code', {
            provider: 'ollama',
            api: 'ollama',
            controls: ['temperature', 'think', 'reasoning_effort'],
            thinkingControl: 'reasoning_effort',
            thinkingDefault: 'medium',
        });

        expect(preset).toEqual({
            temperature: 0.3,
            think: true,
            reasoning_effort: 'medium',
        });
    });

    it('retains manual budgets for older Claude models', () => {
        const preset = resolvePreset('code', {
            provider: 'anthropic',
            api: 'anthropic_messages',
            controls: ['temperature', 'think', 'thinking_budget'],
            thinkingControl: 'thinking_budget',
            thinkingDefault: 'standard',
        });

        expect(preset).toEqual({
            temperature: 1,
            think: true,
            thinking_budget: 'standard',
        });
    });

    it('does not add sampling fields to Bedrock thinking presets', () => {
        const capabilities = {
            provider: 'aperture',
            api: 'bedrock_model_invoke',
            controls: ['think', 'reasoning_effort'],
            thinkingControl: 'reasoning_effort',
            thinkingDefault: 'high',
        };

        expect(resolvePreset('code', capabilities)).toEqual({
            think: true,
            reasoning_effort: 'high',
        });
    });
});
