// MCP descriptions are instructions for the model, not user-facing copy.
// This presentation boundary leaves the original operation metadata intact.
export function operationTitle(operation) {
    return operation.title || operation.id.replace(/^mcp\./, '');
}

export function operationDescription(operation) {
    return operation.id.startsWith('mcp.') ? '' : operation.description || '';
}
