import { describe, expect, it } from 'vitest';

import { buildCliAuthBlob, normalizePathPrefix, splitCommand } from '../providers.js';

describe('splitCommand', () => {
    it('splits a plain space-separated command', () => {
        expect(splitCommand('python /opt/script.py')).toEqual(['python', '/opt/script.py']);
    });

    it('collapses repeated whitespace', () => {
        expect(splitCommand('python   /opt/script.py')).toEqual(['python', '/opt/script.py']);
    });

    it('keeps a double-quoted argument with a space as one token', () => {
        expect(splitCommand('"/home/omnideck/My Scripts/run.sh"')).toEqual([
            '/home/omnideck/My Scripts/run.sh',
        ]);
    });

    it('keeps a single-quoted argument with a space as one token', () => {
        expect(splitCommand("'/home/omnideck/My Scripts/run.sh' --flag")).toEqual([
            '/home/omnideck/My Scripts/run.sh',
            '--flag',
        ]);
    });

    it('mixes quoted and unquoted tokens', () => {
        expect(splitCommand('python "/path with space/run.py" --verbose')).toEqual([
            'python',
            '/path with space/run.py',
            '--verbose',
        ]);
    });

    it('returns an empty array for a blank string', () => {
        expect(splitCommand('')).toEqual([]);
    });

    it('trims surrounding whitespace', () => {
        expect(splitCommand('  bin  ')).toEqual(['bin']);
    });

    it('throws on an unclosed double quote instead of matching it literally', () => {
        expect(() => splitCommand('foo "bar')).toThrow(/unbalanced quote/i);
    });

    it('throws on an unclosed single quote', () => {
        expect(() => splitCommand("foo 'bar")).toThrow(/unbalanced quote/i);
    });

    it('does not throw when quotes of one type are balanced but the other type is absent', () => {
        expect(splitCommand('foo "bar baz" qux')).toEqual(['foo', 'bar baz', 'qux']);
    });
});

describe('normalizePathPrefix', () => {
    it('strips leading and trailing slashes', () => {
        expect(normalizePathPrefix('/repo/')).toBe('repo');
    });

    it('leaves an interior slash alone', () => {
        expect(normalizePathPrefix('repo/sub')).toBe('repo/sub');
    });

    it('collapses a run of only slashes to empty', () => {
        expect(normalizePathPrefix('///')).toBe('');
    });

    it('collapses a blank string to empty', () => {
        expect(normalizePathPrefix('   ')).toBe('');
    });

    it('is idempotent for an already-clean value', () => {
        expect(normalizePathPrefix('repo')).toBe('repo');
    });
});

describe('buildCliAuthBlob', () => {
    it('splits the command and builds the vars dict', () => {
        expect(buildCliAuthBlob({
            command: 'python /opt/script.py',
            vars: [{ name: 'SLACK_TOKEN', value: 'xoxb-abc' }, { name: '', value: 'ignored' }],
            pathPrefix: null,
        })).toEqual({
            command: ['python', '/opt/script.py'],
            vars: { SLACK_TOKEN: 'xoxb-abc' },
            path_prefix: null,
        });
    });

    it('passes the resolved path prefix through unchanged', () => {
        expect(buildCliAuthBlob({
            command: 'bin', vars: [{ name: 'X', value: 'y' }], pathPrefix: 'repo',
        })).toEqual({
            command: ['bin'],
            vars: { X: 'y' },
            path_prefix: 'repo',
        });
    });
});
