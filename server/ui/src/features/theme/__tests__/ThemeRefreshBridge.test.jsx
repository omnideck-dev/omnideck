import { render } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { AppEffectsProvider, useAppEffectDispatch } from '../../app/AppEffects.jsx';
import { APP_EFFECT_TYPES } from '../../app/appEffectTypes.js';
import ThemeRefreshBridge from '../ThemeRefreshBridge.jsx';
import { requestThemeRefresh } from '../themeStylesheet.js';

vi.mock('../themeStylesheet.js', () => ({ requestThemeRefresh: vi.fn() }));

function Dispatcher({ effect }) {
    const dispatch = useAppEffectDispatch();
    return <button type="button" onClick={() => dispatch(effect)}>dispatch</button>;
}

function renderWithEffect(type) {
    return render(
        <AppEffectsProvider>
            <ThemeRefreshBridge />
            <Dispatcher effect={{ type, payload: null }} />
        </AppEffectsProvider>,
    );
}

describe('ThemeRefreshBridge', () => {
    beforeEach(() => {
        vi.mocked(requestThemeRefresh).mockClear();
    });

    it('re-checks the saved theme when a theme refresh is requested', () => {
        const { getByText } = renderWithEffect(APP_EFFECT_TYPES.REFRESH_THEME_REQUESTED);

        getByText('dispatch').click();

        expect(requestThemeRefresh).toHaveBeenCalledTimes(1);
    });

    it('ignores unrelated effects', () => {
        const { getByText } = renderWithEffect(APP_EFFECT_TYPES.REFRESH_CUSTOM_TOOLS_REQUESTED);

        getByText('dispatch').click();

        expect(requestThemeRefresh).not.toHaveBeenCalled();
    });
});
