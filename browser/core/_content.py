"""HTML snapshots of composed browser documents."""

CONTENT_HTML_JS = r"""() => {
    // Import into an inert document so copying custom elements cannot run
    // their constructors or change the live document and its slot assignments.
    const snapshot = document.implementation.createHTMLDocument('');
    function copy(node) {
        if (node.nodeType !== Node.ELEMENT_NODE) {
            return snapshot.importNode(node, false);
        }
        if (node instanceof HTMLTemplateElement) {
            return snapshot.importNode(node, true);
        }
        const clone = snapshot.importNode(node, false);
        let children = node.childNodes;
        if (node.shadowRoot) {
            // Light children appear only where the shadow tree distributes them.
            children = node.shadowRoot.childNodes;
        } else if (node instanceof HTMLSlotElement && node.getRootNode() instanceof ShadowRoot) {
            const assigned = node.assignedNodes({flatten: true});
            children = assigned.length ? assigned : node.childNodes;
        }
        for (const child of children) {
            clone.appendChild(copy(child));
        }
        return clone;
    }
    const doctype = document.doctype ? new XMLSerializer().serializeToString(document.doctype) : '';
    return doctype + (document.documentElement ? copy(document.documentElement).outerHTML : '');
}"""
