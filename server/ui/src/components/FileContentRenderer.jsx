import { lazy, Suspense } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { PreCodeBlock, InlineCode } from './CodeBlock.jsx';
import MarkdownLink from './MarkdownLink.jsx';

// Code-split the editor: CodeMirror is heavy and only needed once a text source
// is actually opened, so keep it out of the initial bundle.
const CodeEditor = lazy(() => import('./CodeEditor.jsx'));

const _markdownComponents = {
    pre: (props) => <PreCodeBlock {...props} />,
    code: (props) => <InlineCode {...props} />,
    a: MarkdownLink,
};

export default function FileContentRenderer({
    item,
    viewMode,
    text,
    draft,
    onDraftChange,
    isMarkdown,
    isHtml,
    isImageFile,
    isPdf,
    iframeSrc,
    pdfSrc,
    imageSrc,
    styles,
}) {
    const { filename, content_type, content } = item;

    return (
        <>
            {isPdf && pdfSrc && (
                <iframe
                    className={styles.pdfFrame || styles.htmlFrame}
                    src={pdfSrc}
                    title={filename}
                />
            )}
            {isPdf && !pdfSrc && (
                <div className={styles.statusText}>Loading...</div>
            )}
            {!isPdf && !isImageFile && viewMode === 'source' && (
                text == null ? (
                    <pre className={styles.sourceCode}>Loading...</pre>
                ) : (
                    <Suspense fallback={<pre className={styles.sourceCode}>Loading...</pre>}>
                        <CodeEditor
                            value={draft}
                            onChange={onDraftChange}
                            filename={filename}
                            contentType={content_type}
                        />
                    </Suspense>
                )
            )}
            {!isPdf && viewMode === 'preview' && isMarkdown && text && (
                <div className={styles.markdownContent}>
                    <ReactMarkdown
                        remarkPlugins={[remarkGfm]}
                        components={_markdownComponents}
                    >
                        {text}
                    </ReactMarkdown>
                </div>
            )}
            {!isPdf && viewMode === 'preview' && isMarkdown && !text && (
                <div className={styles.statusText}>Loading...</div>
            )}
            {!isPdf && viewMode === 'preview' && isHtml && iframeSrc && (
                <iframe
                    className={styles.htmlFrame}
                    src={iframeSrc}
                    title={filename}
                    sandbox="allow-scripts allow-same-origin"
                />
            )}
            {!isPdf && viewMode === 'preview' && isHtml && !iframeSrc && (
                <div className={styles.statusText}>Loading...</div>
            )}
            {!isPdf && isImageFile && (
                <div className={styles.imageContainer}>
                    {content && (
                        <img
                            src={`data:${content_type};base64,${content}`}
                            alt={filename}
                            className={styles.image}
                        />
                    )}
                    {imageSrc && !content && (
                        <img src={imageSrc} alt={filename} className={styles.image} />
                    )}
                </div>
            )}
        </>
    );
}
