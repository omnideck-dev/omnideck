import { useMemo } from 'react';
import CodeMirror from '@uiw/react-codemirror';
import { EditorView } from '@codemirror/view';
import { editorLanguageExtension } from '../utils/editorLanguage.js';
import { useTheme } from '../contexts/Theme.jsx';
import styles from './CodeEditor.module.css';

/**
 * A source-code editor for the preview panel. Wraps CodeMirror with the file's
 * language mode (syntax highlighting, auto-indent, bracket matching) and wires
 * its value up to the caller's edit buffer. Always editable — the preview
 * panel's source view is an edit view.
 */
export default function CodeEditor({ value, onChange, filename, contentType }) {
    const { dark } = useTheme();
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
