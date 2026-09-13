import { describe, expect, it } from 'vitest';

import {
    isSupported,
    resolveInferenceCapabilities,
    sanitizeInferenceOptions,
    sanitizeProfileForModel,
} from '../inferenceConstants.js';

describe('resolveInferenceCapabilities', () => {
    it('uses discovered Responses controls for an Aperture GPT model', () => {
        const capabilities = resolveInferenceCapabilities('aperture', {
            name: 'bedrock/openai.gpt-5.6-luna',
            wire_api: 'Responses',
            inference_api: 'openai_responses',
            inference_controls: [
                'context_window', 'num_predict',
                'max_iterations', 'compaction_threshold', 'think',
                'reasoning_effort', 'reasoning_summary',
            ],
            reasoning_efforts: ['none', 'low', 'medium', 'high', 'xhigh', 'max'],
            supports_thinking: true,
            context_window: 1_050_000,
            max_output_tokens: 128_000,
            upstream_provider: 'Amazon Bedrock',
        });

        expect(capabilities.api).toBe('openai_responses');
        expect(capabilities.detected).toBe(true);
        expect(capabilities.reasoningEfforts).toEqual([
            'none', 'low', 'medium', 'high', 'xhigh', 'max',
        ]);
        expect(capabilities.thinkingControl).toBe('reasoning_effort');
        expect(capabilities.thinkingLevels).toEqual([
            'none', 'low', 'medium', 'high', 'xhigh', 'max',
        ]);
        expect(isSupported('reasoning_effort', capabilities)).toBe(true);
        expect(isSupported('temperature', capabilities)).toBe(false);
        expect(isSupported('top_p', capabilities)).toBe(false);
        expect(isSupported('thinking_budget', capabilities)).toBe(false);
    });

    it('uses Anthropic controls for a Bedrock Claude model under the same provider', () => {
        const capabilities = resolveInferenceCapabilities('aperture', {
            name: 'bedrock/us.anthropic.claude-sonnet-4-6',
            wire_api: 'Amazon Bedrock',
            inference_api: 'bedrock_model_invoke',
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

    it('falls back to provider defaults when model metadata is unavailable', () => {
        const capabilities = resolveInferenceCapabilities('anthropic');

        expect(capabilities.detected).toBe(false);
        expect(isSupported('top_k', capabilities)).toBe(true);
        expect(isSupported('thinking_budget', capabilities)).toBe(true);
        expect(isSupported('reasoning_summary', capabilities)).toBe(false);
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
            inference_controls: ['temperature', 'top_p', 'context_window', 'num_predict'],
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
            name: 'bedrock/openai.gpt-5.6-luna',
            inference_api: 'openai_responses',
            inference_controls: [
                'temperature', 'top_p', 'context_window', 'num_predict',
                'max_iterations', 'compaction_threshold', 'think', 'reasoning_effort',
            ],
            reasoning_efforts: ['none', 'low', 'medium', 'high', 'xhigh', 'max'],
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
