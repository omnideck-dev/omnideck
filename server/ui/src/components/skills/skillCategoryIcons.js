// Bootstrap Icons glyph per tool-category id. The backend catalog carries no
// icon, so the UI maps one here; an unknown id falls back to a generic glyph.
const CATEGORY_ICONS = {
    coding: 'bi-terminal',
    browser: 'bi-globe2',
    webfetch: 'bi-cloud-arrow-down',
    memory: 'bi-bookmark-star',
    planning: 'bi-diagram-3',
    image_generation: 'bi-image',
    music_generation: 'bi-music-note-beamed',
    desktop: 'bi-display',
    custom_tools: 'bi-tools',
    email: 'bi-envelope',
    calendar: 'bi-calendar-event',
    drive: 'bi-folder',
    contacts: 'bi-person-lines-fill',
    http: 'bi-hdd-network',
};

export function categoryIcon(id) {
    return CATEGORY_ICONS[id] || 'bi-puzzle';
}
