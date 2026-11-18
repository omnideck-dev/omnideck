import { useAppEffectSubscription } from '../app/AppEffects.jsx';
import { APP_EFFECT_TYPES } from '../app/appEffectTypes.js';
import { requestThemeRefresh } from './themeStylesheet.js';

/** Re-checks the saved theme whenever a conversation reports that it was changed. */
export default function ThemeRefreshBridge() {
    useAppEffectSubscription(APP_EFFECT_TYPES.REFRESH_THEME_REQUESTED, requestThemeRefresh);
    return null;
}
