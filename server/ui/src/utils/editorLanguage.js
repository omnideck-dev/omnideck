import { javascript } from '@codemirror/lang-javascript';
import { python } from '@codemirror/lang-python';
import { html } from '@codemirror/lang-html';
import { xml } from '@codemirror/lang-xml';
import { css } from '@codemirror/lang-css';
import { json } from '@codemirror/lang-json';
import { markdown } from '@codemirror/lang-markdown';
import { yaml } from '@codemirror/lang-yaml';
import { sql } from '@codemirror/lang-sql';
import { rust } from '@codemirror/lang-rust';
import { cpp } from '@codemirror/lang-cpp';
import { java } from '@codemirror/lang-java';
import { php } from '@codemirror/lang-php';
import { go } from '@codemirror/lang-go';
import { resolveLanguage } from './highlight.js';

// Reuse the highlight.js language resolution (filename + content-type) and map
// its language names onto CodeMirror language packages. Names without a bundled
// package (ruby, kotlin, bash, …) fall through to plain text — still fully
// editable, just without syntax-aware indentation.
const LANG_TO_EXTENSION = {
    javascript: () => javascript({ jsx: true }),
    typescript: () => javascript({ jsx: true, typescript: true }),
    python: () => python(),
    css: () => css(),
    scss: () => css(),
    less: () => css(),
    json: () => json(),
    markdown: () => markdown(),
    yaml: () => yaml(),
    sql: () => sql(),
    rust: () => rust(),
    c: () => cpp(),
    cpp: () => cpp(),
    java: () => java(),
    php: () => php(),
    go: () => go(),
};

/**
 * Resolve the CodeMirror language extension for a file, or null for plain text.
 */
export function editorLanguageExtension({ filename, contentType } = {}) {
    const lang = resolveLanguage({ filename, contentType });
    if (!lang) return null;
    // hljs collapses HTML and XML into one 'xml' language; split them back apart
    // so real HTML gets the tag-aware HTML mode and .xml/.svg get the XML mode.
    if (lang === 'xml') {
        const isHtml = contentType === 'text/html' || /\.html?$/i.test(filename || '');
        return isHtml ? html() : xml();
    }
    const make = LANG_TO_EXTENSION[lang];
    return make ? make() : null;
}
