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

describe('Select source policy', () => {
    it('routes ordinary dropdowns through the shared primitive', () => {
        const violations = sourceFiles(SOURCE_ROOT).flatMap((path) => {
            const source = readFileSync(path, 'utf8');
            return /<select\b/.test(source) ? [relative(SOURCE_ROOT, path)] : [];
        });

        expect(violations, 'Native <select> controls bypass the cross-WebView visual contract')
            .toEqual([]);
    });
});
