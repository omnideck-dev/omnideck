import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import DayHeader, { dayLabel } from '../DayHeader.jsx';

describe('DayHeader', () => {
    it('labels a day header with the day', () => {
        render(<DayHeader timestamp={new Date().toISOString()} />);
        expect(screen.getByTestId('day-header')).toHaveTextContent('Today');
        expect(screen.getByRole('separator', { name: 'Today' })).toBeInTheDocument();
    });

    it('names yesterday and shows a date for older days', () => {
        const yesterday = new Date();
        yesterday.setDate(yesterday.getDate() - 1);
        expect(dayLabel(yesterday.toISOString())).toBe('Yesterday');
        expect(dayLabel('2020-03-04T12:00:00')).not.toMatch(/Today|Yesterday/);
    });
});
