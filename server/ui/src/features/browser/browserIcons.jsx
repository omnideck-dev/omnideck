export const BROWSER_PROFILE_ICONS = [
    'bi-globe2', 'bi-person', 'bi-briefcase', 'bi-envelope',
    'bi-building', 'bi-shop', 'bi-bank', 'bi-book', 'bi-mortarboard',
    'bi-code-slash', 'bi-palette', 'bi-camera', 'bi-music-note-beamed',
    'bi-star', 'bi-heart', 'bi-house', 'bi-shield-lock', 'bi-cloud', 'bi-rocket',
    'bi-linkedin', 'bi-google', 'bi-microsoft', 'bi-microsoft-teams', 'bi-apple',
    'bi-github', 'bi-gitlab', 'bi-slack', 'bi-discord', 'bi-dropbox',
    'bi-facebook', 'bi-instagram', 'bi-twitter-x', 'bi-reddit', 'bi-stripe',
    'bi-paypal', 'bi-amazon', 'bi-openai', 'bi-youtube', 'bi-whatsapp',
    'bi-telegram',
];

export function BrowserProfileIcon({ icon, className = '' }) {
    const resolved = BROWSER_PROFILE_ICONS.includes(icon) ? icon : 'bi-globe2';
    return <i className={`bi ${resolved} ${className}`} aria-hidden="true" />;
}
