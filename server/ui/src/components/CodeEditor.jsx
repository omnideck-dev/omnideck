import { useEffect, useMemo, useState } from 'react';
import CodeMirror from '@uiw/react-codemirror';
import { EditorView } from '@codemirror/view';
import { editorLanguageExtension } from '../utils/editorLanguage.js';
import styles from './CodeEditor.module.css';

function _readDark() {
    if (typeof document === 'undefined') return false;
    return document.documentElement.getAttribute('data-theme') === 'dark';
}

// Follow the app's theme from the single source of truth (the data-theme
// attribute on <html>) rather than a prop, so the editor matches its
// surroundings no matter which view mounts it.
function useIsDarkTheme() {
    const [dark, setDark] = useState(_readDark);
    useEffect(() => {
        const root = document.documentElement;
        const observer = new MutationObserver(() => setDark(_readDark()));
        observer.observe(root, { attributes: true, attributeFilter: ['data-theme'] });
        setDark(_readDark());
        return () => observer.disconnect();
    }, []);
    return dark;
}

/**
 * A source-code editor for the preview panel. Wraps CodeMirror with the file's
 * language mode (syntax highlighting, auto-indent, bracket matching) and wires
 * its value up to the caller's edit buffer. Always editable — the preview
 * panel's source view is an edit view.
 */
export default function CodeEditor({ value, onChange, filename, contentType }) {
    const dark = useIsDarkTheme();
    const extensions = useMemo(() => {
        const exts = [EditorView.lineWrapping];
        const lang = editorLanguageExtension({ filename, contentType });
        if (lang) exts.push(lang);
        return exts;
    }, [filename, contentType]);

    return (
        <CodeMirror
            className={styles.editor}
            value={value ?? ''}
            onChange={onChange}
            extensions={extensions}
            theme={dark ? 'dark' : 'light'}
            height="100%"
            basicSetup={{
                lineNumbers: true,
                highlightActiveLine: true,
                bracketMatching: true,
                closeBrackets: true,
                autocompletion: false,
                foldGutter: true,
            }}
            data-testid="code-editor"
        />
    );
}
