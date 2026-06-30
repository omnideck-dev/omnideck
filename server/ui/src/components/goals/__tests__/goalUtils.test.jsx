import { expect, test } from 'vitest';

import { formatCron } from '../goalUtils.jsx';

test('humanizes daily schedules with a friendly time', () => {
    expect(formatCron('0 9 * * *')).toBe('Daily at 9 AM');
    expect(formatCron('30 14 * * *')).toBe('Daily at 2:30 PM');
    expect(formatCron('0 0 * * *')).toBe('Daily at 12 AM');
});

test('humanizes weekday / weekend / single-day schedules', () => {
    expect(formatCron('0 9 * * 1-5')).toBe('Weekdays at 9 AM');
    expect(formatCron('0 9 * * 0,6')).toBe('Weekends at 9 AM');
    expect(formatCron('0 9 * * 1')).toBe('Mon at 9 AM');
});

test('humanizes sub-hour and hourly cadences', () => {
    expect(formatCron('* * * * *')).toBe('Every minute');
    expect(formatCron('*/15 * * * *')).toBe('Every 15 minutes');
    expect(formatCron('0 * * * *')).toBe('Every hour');
    expect(formatCron('0 */6 * * *')).toBe('Every 6 hours');
});

test('humanizes monthly schedules', () => {
    expect(formatCron('0 0 1 * *')).toBe('Monthly on the 1st at 12 AM');
});

test('never leaks raw cron: empty is a dash, unparseable is "Custom schedule"', () => {
    expect(formatCron('')).toBe('-');
    expect(formatCron('not a cron')).toBe('Custom schedule');
    expect(formatCron('15 10 3 6 2')).toBe('Custom schedule'); // specific month — not modeled
});
