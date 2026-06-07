import React from 'react';

// Anchor renderer for markdown links: always open in a new tab and drop the
// opener reference so the new page can't reach back via window.opener.
export default function MarkdownLink({ node, ...props }) {
    return <a {...props} target="_blank" rel="noopener noreferrer" />;
}
