import { readdirSync, readFileSync } from 'node:fs';
import { extname, join, relative } from 'node:path';
import { describe, expect, it } from 'vitest';

const SOURCE_ROOT = join(process.cwd(), 'src');

function sourceFiles(directory) {
    return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
        const path = join(directory, entry.name);
        if (entry.isDirectory()) return entry.name === '__tests__' ? [] : sourceFiles(path);
        return ['.js', '.jsx', '.ts', '.tsx'].includes(extname(path)) ? [path] : [];
    });
}

function styleFiles(directory) {
    return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
        const path = join(directory, entry.name);
        if (entry.isDirectory()) return styleFiles(path);
        return extname(path) === '.css' ? [path] : [];
    });
}

describe('Select source policy', () => {
    it('routes ordinary dropdowns through the shared primitive', () => {
        const violations = sourceFiles(SOURCE_ROOT).flatMap((path) => {
            const source = readFileSync(path, 'utf8');
            return /<select\b/.test(source) ? [relative(SOURCE_ROOT, path)] : [];
        });

        expect(violations, 'Native <select> controls bypass the cross-WebView visual contract')
            .toEqual([]);
    });

    it('keeps every shared select at the SIGNAL height and font family', () => {
        const selectStyles = readFileSync(
            join(SOURCE_ROOT, 'components/primitives/Select.module.css'),
            'utf8',
        );
        const heightOverrides = styleFiles(SOURCE_ROOT).flatMap((path) => {
            const source = readFileSync(path, 'utf8');
            return /--select-height\s*:/.test(source) ? [relative(SOURCE_ROOT, path)] : [];
        });
        const familyOverrides = styleFiles(SOURCE_ROOT).flatMap((path) => {
            const source = readFileSync(path, 'utf8');
            return /--select-font-family\s*:/.test(source)
                ? [relative(SOURCE_ROOT, path)]
                : [];
        });

        expect(selectStyles).toMatch(/\.trigger\s*\{[\s\S]*?height:\s*32px;/);
        expect(selectStyles).toMatch(/font-family:\s*var\(--font-body\);/);
        expect(heightOverrides, 'Select height is a shared SIGNAL constant').toEqual([]);
        expect(familyOverrides, 'Selects use the SIGNAL body font family').toEqual([]);
    });
});
