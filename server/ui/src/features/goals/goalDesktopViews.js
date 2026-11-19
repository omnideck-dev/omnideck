export const GOAL_VIEW_ID = 'goal';
export const GOALS_VIEW_ID = 'destination:goals';

export function goalTabLabel(title) {
    const words = (title || '').trim().split(/\s+/).filter(Boolean).slice(0, 3).join(' ');
    if (!words) return 'Goal';
    return `Goal · ${words.length > 24 ? `${words.slice(0, 23).trimEnd()}…` : words}`;
}

export function goalDesktopView(label = 'Goal') {
    return {
        id: GOAL_VIEW_ID,
        type: 'goal',
        label,
        icon: 'bi-bullseye',
        identity: {},
        closable: true,
    };
}
