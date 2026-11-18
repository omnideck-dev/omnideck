import { describe, expect, it } from 'vitest';

import {
    isAvailable,
    isSupported,
    resolveInferenceCapabilities,
    sanitizeInferenceOptions,
    sanitizeProfileForModel,
} from '../inferenceConstants.js';

describe('resolveInferenceCapabilities', () => {
    it('uses discovered Responses controls for an Aperture GPT model', () => {
        const capabilities = resolveInferenceCapabilities('aperture', {
            name: 'gpt-5.6-luna',
            wire_api: 'Responses',
            inference_api: 'openai_responses',
            inference_controls: [
                'num_predict', 'max_iterations', 'compaction_threshold', 'think',
                'reasoning_effort', 'reasoning_summary',
            ],
            supports_thinking: true,
            thinking_control: 'reasoning_effort',
            thinking_levels: ['none', 'low', 'medium', 'high', 'xhigh', 'max'],
            context_window: 1_050_000,
            max_output_tokens: 128_000,
        });

        expect(capabilities.api).toBe('openai_responses');
        expect(capabilities.detected).toBe(true);
        expect(isSupported('context_window', capabilities)).toBe(false);
        expect(capabilities.thinkingControl).toBe('reasoning_effort');
        expect(capabilities.thinkingLevels).toEqual([
            'none', 'low', 'medium', 'high', 'xhigh', 'max',
        ]);
        expect(isSupported('reasoning_effort', capabilities)).toBe(true);
        expect(isSupported('temperature', capabilities)).toBe(false);
        expect(isSupported('top_p', capabilities)).toBe(false);
        expect(isSupported('thinking_budget', capabilities)).toBe(false);
    });

    it('uses Anthropic controls for a Claude model under the same provider', () => {
        const capabilities = resolveInferenceCapabilities('aperture', {
            name: 'claude-sonnet-4-6',
            wire_api: 'Anthropic Messages',
            inference_api: 'anthropic_messages',
            inference_controls: [
                'context_window', 'num_predict', 'max_iterations', 'compaction_threshold',
                'think', 'reasoning_effort',
            ],
            supports_thinking: true,
            thinking_control: 'reasoning_effort',
            thinking_levels: ['low', 'medium', 'high', 'max'],
            thinking_default: 'high',
        });

        expect(isSupported('temperature', capabilities)).toBe(false);
        expect(isSupported('top_k', capabilities)).toBe(false);
        expect(isSupported('top_p', capabilities)).toBe(false);
        expect(isSupported('thinking_budget', capabilities)).toBe(false);
        expect(isSupported('reasoning_effort', capabilities)).toBe(true);
        expect(isSupported('reasoning_summary', capabilities)).toBe(false);
        expect(capabilities.thinkingControl).toBe('reasoning_effort');
        expect(capabilities.thinkingLevels).toEqual(['low', 'medium', 'high', 'max']);
        expect(capabilities.thinkingDefault).toBe('high');
    });

    it('honors an explicit non-thinking model descriptor', () => {
        const capabilities = resolveInferenceCapabilities('aperture', {
            name: 'openai/gpt-4.1',
            inference_api: 'openai_responses',
            inference_controls: ['temperature', 'top_p', 'num_predict', 'max_iterations'],
            supports_thinking: false,
        });

        expect(isSupported('think', capabilities)).toBe(false);
        expect(isSupported('reasoning_effort', capabilities)).toBe(false);
    });

    it('offers no model settings until the model details arrive', () => {
        const capabilities = resolveInferenceCapabilities('anthropic');

        expect(capabilities.detected).toBe(false);
        expect(capabilities.controls).toEqual([]);
        expect(isSupported('temperature', capabilities)).toBe(false);
        expect(isSupported('think', capabilities)).toBe(false);
    });

    it('uses model-provided Ollama thinking levels and required-thinking metadata', () => {
        const capabilities = resolveInferenceCapabilities('ollama', {
            name: 'gpt-oss:20b',
            inference_api: 'ollama',
            inference_controls: ['think', 'reasoning_effort'],
            thinking_control: 'reasoning_effort',
            thinking_levels: ['low', 'medium', 'high'],
            thinking_required: true,
        });

        expect(capabilities.thinkingLevels).toEqual(['low', 'medium', 'high']);
        expect(capabilities.thinkingRequired).toBe(true);
    });

    it('removes legacy Ollama overrides from an Aperture Responses model', () => {
        const capabilities = resolveInferenceCapabilities('aperture', {
            name: 'openai.gpt-5.6-luna',
            inference_api: 'openai_responses',
            inference_controls: ['temperature', 'top_p', 'num_predict'],
        });

        expect(sanitizeInferenceOptions({
            temperature: 0.3,
            top_k: 20,
            num_ctx: 60_000,
            num_predict: 512,
        }, capabilities)).toEqual({
            temperature: 0.3,
            num_predict: 512,
        });
    });

    it('clears hidden model-specific profile values when switching to cloud', () => {
        const modelInfo = {
            name: 'gpt-5.6-luna',
            inference_api: 'openai_responses',
            inference_controls: [
                'temperature', 'top_p', 'num_predict',
                'max_iterations', 'compaction_threshold', 'think', 'reasoning_effort',
            ],
            thinking_control: 'reasoning_effort',
            thinking_levels: ['none', 'low', 'medium', 'high', 'xhigh', 'max'],
            context_window: 1_050_000,
        };
        const capabilities = resolveInferenceCapabilities('aperture', modelInfo);

        expect(sanitizeProfileForModel({
            context_window: 32_000,
            top_k: 40,
            repeat_penalty: 1.1,
            thinking_budget: 'extended',
            reasoning_effort: 'minimal',
            num_predict: 2048,
        }, capabilities, modelInfo)).toEqual({
            context_window: null,
            top_k: null,
            repeat_penalty: null,
            thinking_budget: null,
            reasoning_effort: null,
            reasoning_summary: null,
            num_predict: 2048,
        });
    });

    it('drops a stale context allocation when cloud metadata has no limit', () => {
        const capabilities = resolveInferenceCapabilities('openai_compat');

        expect(sanitizeProfileForModel(
            { context_window: 32_000 }, capabilities,
        ).context_window).toBeNull();
    });
});

describe('values the model refuses', () => {
    const olderClaude = resolveInferenceCapabilities('anthropic', {
        name: 'claude-sonnet-4-5',
        inference_api: 'anthropic_messages',
        inference_controls: ['temperature', 'top_p', 'top_k', 'think', 'thinking_budget'],
        supports_thinking: true,
        thinking_control: 'thinking_budget',
        thinking_excluded_controls: ['temperature', 'top_k'],
        exclusive_controls: [['temperature', 'top_p']],
    });

    it('hides fields that thinking turns off only while thinking', () => {
        expect(isAvailable('temperature', olderClaude, false)).toBe(true);
        expect(isAvailable('temperature', olderClaude, true)).toBe(false);
        expect(isAvailable('top_p', olderClaude, true)).toBe(true);
    });

    it('takes refusal rules only from the model details', () => {
        const capabilities = resolveInferenceCapabilities('openai', {
            inference_api: 'openai_responses',
            inference_controls: ['temperature', 'top_p', 'think', 'reasoning_effort'],
        });

        expect(capabilities.thinkingExcludedControls).toEqual([]);
        expect(capabilities.exclusiveControls).toEqual([]);
    });

    it('clears refused values when a profile moves to the model', () => {
        const next = sanitizeProfileForModel(
            { think: false, temperature: 0.4, top_p: 0.9, top_k: 20 },
            olderClaude,
        );

        expect(next).toMatchObject({ temperature: 0.4, top_p: null, top_k: 20 });
    });

    it('clears fields thinking turns off when the profile thinks', () => {
        const next = sanitizeProfileForModel(
            { think: true, temperature: 0.4, top_k: 20, top_p: 0.97 },
            olderClaude,
        );

        expect(next).toMatchObject({ temperature: null, top_k: null, top_p: 0.97 });
    });

    it('drops refused option overrides for helper models', () => {
        expect(sanitizeInferenceOptions(
            { temperature: 0.4, top_p: 0.9, top_k: 20 },
            olderClaude,
            { think: true },
        )).toEqual({ top_p: 0.9 });
    });
});
