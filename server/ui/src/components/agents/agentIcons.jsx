export const AGENT_ICONS = [
    'bi-robot', 'bi-search', 'bi-bookshelf', 'bi-envelope', 'bi-calendar3', 'bi-pencil',
    'bi-lightbulb', 'bi-bar-chart', 'bi-bullseye', 'bi-flower1', 'bi-house', 'bi-briefcase',
    'bi-person', 'bi-people', 'bi-globe2', 'bi-journal-text', 'bi-palette', 'bi-star',
];

// Older saved profiles may have emoji icons; show the default until a new icon is chosen.
export function resolveAgentIcon(icon) {
    return AGENT_ICONS.includes(icon) ? icon : 'bi-robot';
}

export function AgentIcon({ icon }) {
    return <i className={`bi ${resolveAgentIcon(icon)}`} aria-hidden="true" />;
}
