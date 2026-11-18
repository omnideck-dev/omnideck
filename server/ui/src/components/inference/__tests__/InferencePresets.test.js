import { describe, expect, it } from 'vitest';

import { resolvePreset } from '../InferencePresets.jsx';
import { resolveInferenceCapabilities } from '../inferenceConstants.js';

const PRESET_IDS = ['balanced', 'creative', 'precise', 'code'];

// Model shapes as the server describes them, covering every rule a preset
// could break.
const MODELS = {
    'Claude Opus 5.5, always thinks, no sampling': ['anthropic', {
        inference_api: 'anthropic_messages',
        inference_controls: ['num_predict', 'think', 'reasoning_effort'],
        supports_thinking: true,
        thinking_control: 'reasoning_effort',
        thinking_levels: ['low', 'medium', 'high', 'xhigh', 'max'],
        thinking_default: 'medium',
        thinking_required: true,
        thinking_excluded_controls: [],
        exclusive_controls: [],
    }],
    'Claude Sonnet 4.5, token budget, refuses pairs': ['anthropic', {
        inference_api: 'anthropic_messages',
        inference_controls: ['temperature', 'top_p', 'top_k', 'num_predict', 'think', 'thinking_budget'],
        supports_thinking: true,
        thinking_control: 'thinking_budget',
        thinking_levels: ['minimal', 'standard', 'extended'],
        thinking_default: 'standard',
        thinking_excluded_controls: ['temperature', 'top_k'],
        exclusive_controls: [['temperature', 'top_p']],
    }],
    'GPT on Responses, no sampling': ['aperture', {
        inference_api: 'openai_responses',
        inference_controls: ['num_predict', 'think', 'reasoning_effort', 'reasoning_summary'],
        supports_thinking: true,
        thinking_control: 'reasoning_effort',
        thinking_levels: ['none', 'low', 'medium', 'high', 'xhigh', 'max'],
        thinking_default: 'medium',
        thinking_excluded_controls: [],
        exclusive_controls: [],
    }],
    'Chat model on Responses with sampling': ['openai', {
        inference_api: 'openai_responses',
        inference_controls: ['temperature', 'top_p', 'num_predict', 'think', 'reasoning_effort'],
        supports_thinking: true,
        thinking_control: 'reasoning_effort',
        thinking_levels: ['low', 'medium', 'high'],
        thinking_default: 'medium',
        thinking_excluded_controls: ['temperature', 'top_p'],
        exclusive_controls: [],
    }],
    'OpenRouter model without thinking': ['openrouter', {
        inference_api: 'openai_chat',
        inference_controls: ['temperature', 'top_p', 'num_predict'],
        supports_thinking: false,
        thinking_excluded_controls: [],
        exclusive_controls: [],
    }],
    'Ollama model that can think': ['ollama', {
        inference_api: 'ollama',
        inference_controls: ['temperature', 'top_p', 'top_k', 'repeat_penalty', 'num_predict', 'think', 'reasoning_effort'],
        supports_thinking: true,
        thinking_control: 'reasoning_effort',
        thinking_levels: ['low', 'medium', 'high', 'max'],
        thinking_default: 'medium',
        thinking_excluded_controls: [],
        exclusive_controls: [],
    }],
    'Ollama GPT-OSS, always thinks': ['ollama', {
        inference_api: 'ollama',
        inference_controls: ['temperature', 'top_p', 'top_k', 'num_predict', 'think', 'reasoning_effort'],
        supports_thinking: true,
        thinking_control: 'reasoning_effort',
        thinking_levels: ['low', 'medium', 'high'],
        thinking_default: 'medium',
        thinking_required: true,
        thinking_excluded_controls: [],
        exclusive_controls: [],
    }],
};

function rejectedValues(values, capabilities) {
    const problems = [];
    const thinking = values.think || capabilities.thinkingRequired;
    for (const field of Object.keys(values)) {
        if (!capabilities.controls.includes(field)) problems.push(`${field} is not accepted`);
        if (thinking && capabilities.thinkingExcludedControls.includes(field)) {
            problems.push(`${field} is refused while thinking`);
        }
    }
    for (const group of capabilities.exclusiveControls) {
        if (group.filter((field) => values[field] != null).length > 1) {
            problems.push(`${group.join(' and ')} are refused together`);
        }
    }
    for (const field of ['reasoning_effort', 'thinking_budget']) {
        if (values[field] != null && !capabilities.thinkingLevels.includes(values[field])) {
            problems.push(`${field} ${values[field]} is not a level this model has`);
        }
    }
    return problems;
}

describe('inference presets', () => {
    describe.each(Object.entries(MODELS))('%s', (_name, [provider, modelInfo]) => {
        const capabilities = resolveInferenceCapabilities(provider, modelInfo);

        it.each(PRESET_IDS)('%s sets only values the model accepts', (presetId) => {
            expect(rejectedValues(resolvePreset(presetId, capabilities), capabilities)).toEqual([]);
        });
    });

    it('thinks at the model default level', () => {
        const [provider, modelInfo] = MODELS['GPT on Responses, no sampling'];
        const capabilities = resolveInferenceCapabilities(provider, modelInfo);

        expect(resolvePreset('code', capabilities)).toEqual({
            think: true,
            reasoning_effort: 'medium',
        });
    });

    it('keeps the first value of a pair the model refuses together', () => {
        const [provider, modelInfo] = MODELS['Claude Sonnet 4.5, token budget, refuses pairs'];
        const capabilities = resolveInferenceCapabilities(provider, modelInfo);

        expect(resolvePreset('creative', capabilities)).toEqual({ temperature: 1.0 });
        expect(resolvePreset('code', capabilities)).toEqual({
            think: true,
            thinking_budget: 'standard',
        });
    });

    it('sets nothing when the model accepts none of the preset values', () => {
        const [provider, modelInfo] = MODELS['Claude Opus 5.5, always thinks, no sampling'];
        const capabilities = resolveInferenceCapabilities(provider, modelInfo);

        expect(resolvePreset('balanced', capabilities)).toEqual({});
    });
});
