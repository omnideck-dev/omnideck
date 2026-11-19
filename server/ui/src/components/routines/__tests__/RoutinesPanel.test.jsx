import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import RoutinesPanel from '../RoutinesPanel.jsx';

describe('RoutinesPanel', () => {
    it('shows active tasks out of the routine limit as N/M slots', () => {
        render(
            <RoutinesPanel
                routines={[]}
                runnerStatus={{ running: true, paused: false, active_tasks: 1, max_concurrent: 4 }}
                onSelectRoutine={() => {}}
            />,
        );
        expect(screen.getByText('1/4 slots')).toBeInTheDocument();
        expect(screen.getByText('Runner: active')).toBeInTheDocument();
    });
});
