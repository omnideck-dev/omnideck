import js from '@eslint/js';
import reactHooks from 'eslint-plugin-react-hooks';
import globals from 'globals';

export default [
    {
        ignores: [
            'dist/**',
            'src/**/__tests__/**',
            'src/**/*.test.*',
            'src/setupTests.js',
        ],
    },
    {
        files: ['src/**/*.{js,jsx}'],
        languageOptions: {
            ecmaVersion: 'latest',
            globals: {
                ...globals.browser,
                ...globals.es2022,
            },
            parserOptions: {
                ecmaFeatures: { jsx: true },
                sourceType: 'module',
            },
        },
        plugins: {
            'react-hooks': reactHooks,
        },
        rules: {
            ...js.configs.recommended.rules,
            // Dead-code cleanup is low signal in this legacy JavaScript UI.
            'no-unused-vars': 'off',
            'react-hooks/rules-of-hooks': 'error',
            // Existing command/context objects intentionally violate the rule's
            // referential-stability assumptions, making it too noisy for agents.
            'react-hooks/exhaustive-deps': 'off',
        },
    },
];
