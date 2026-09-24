import { render, screen, fireEvent } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import CompactionChip from '../CompactionChip.jsx';

const baseStats = {
    when: '2026-05-30T21:34:26.423656',
    context_before: 20000,
    context_after: 12000,
    context_limit: 30000,
    saved_tokens: 8000,
    saved_ratio: 0.4,
    spanned_seconds: 125.5,
    scope: { user_messages: 3, iterations: 4, tool_results: 7 },
    summary_chars: 1200,
    summary_tokens: 300,
    summary_lines: 18,
    elapsed_seconds: 8.4,
    model: 'glm-5:cloud',
};

describe('CompactionChip', () => {
    it('renders a generic chip label with no jargon counts', () => {
        // "Turns" and "iterations" are internal terminology — users
        // don't know what either means. Chip stays plain and the
        // expanded panel shows the concrete things (tool calls,
        // savings, summary size, time).
        render(<CompactionChip stats={baseStats} summaryText="hi" />);
        const chip = screen.getByTestId('compaction-chip');
        expect(chip).toHaveTextContent('earlier conversation compacted');
        expect(chip).not.toHaveTextContent(/turn/);
        expect(chip).not.toHaveTextContent(/iteration/);
    });

    it('uses the same generic label when scope is missing', () => {
        render(<CompactionChip stats={{}} summaryText="hi" />);
        const chip = screen.getByTestId('compaction-chip');
        expect(chip).toHaveTextContent('earlier conversation compacted');
    });

    it('starts closed and opens the panel on click', () => {
        render(<CompactionChip stats={baseStats} summaryText="done stuff" />);
        const details = screen.getByTestId('compaction-row');
        expect(details).not.toHaveAttribute('open');
        fireEvent.click(screen.getByTestId('compaction-chip'));
        expect(details).toHaveAttribute('open');
    });

    it('renders the stats grid when expanded', () => {
        render(<CompactionChip stats={baseStats} summaryText="done" />);
        fireEvent.click(screen.getByTestId('compaction-chip'));
        const panel = screen.getByTestId('compaction-panel');
        // Token formatting: 20000 → 20k, 12000 → 12k
        expect(panel).toHaveTextContent('20k');
        expect(panel).toHaveTextContent('12k');
        // Savings: 8000 saved, 40%
        expect(panel).toHaveTextContent('saved 8k (40%)');
        // Spanned: "2m 6s" (125.5 → floor 2m + round 6s)
        expect(panel).toHaveTextContent('2m 6s');
        // Scope: tool calls only — turns and iterations are jargon.
        expect(panel).toHaveTextContent('7 tool calls');
        expect(panel).not.toHaveTextContent(/turn/);
        expect(panel).not.toHaveTextContent(/iteration/);
        // Summary: token count (lines no longer displayed)
        expect(panel).toHaveTextContent('300 tokens');
        expect(panel).not.toHaveTextContent('18 lines');
        // Took: elapsed + model
        expect(panel).toHaveTextContent('8.4s');
        expect(panel).toHaveTextContent('glm-5:cloud');
    });

    it('hides the savings line when saved_tokens is zero', () => {
        const stats = { ...baseStats, saved_tokens: 0, saved_ratio: 0 };
        render(<CompactionChip stats={stats} summaryText="x" />);
        fireEvent.click(screen.getByTestId('compaction-chip'));
        const panel = screen.getByTestId('compaction-panel');
        expect(panel).not.toHaveTextContent(/saved/);
    });

    it('hides scope row entirely when scope is missing', () => {
        const { scope, ...stats } = baseStats;
        render(<CompactionChip stats={stats} summaryText="x" />);
        fireEvent.click(screen.getByTestId('compaction-chip'));
        const panel = screen.getByTestId('compaction-panel');
        expect(panel).not.toHaveTextContent('tool call');
    });

    it('shows both summary sections with labels when both texts are present', () => {
        render(
            <CompactionChip
                stats={baseStats}
                userIntentSummary="user is asking about X"
                summaryText="agent did Y"
            />,
        );
        fireEvent.click(screen.getByTestId('compaction-chip'));
        const panel = screen.getByTestId('compaction-panel');
        expect(panel).toHaveTextContent('What the agent thinks you are working on');
        expect(panel).toHaveTextContent('user is asking about X');
        expect(panel).toHaveTextContent('What the agent thinks it has done');
        expect(panel).toHaveTextContent('agent did Y');
    });

    it('omits the user-intent section when userIntentSummary is empty', () => {
        render(<CompactionChip stats={baseStats} summaryText="agent did Y" />);
        fireEvent.click(screen.getByTestId('compaction-chip'));
        const panel = screen.getByTestId('compaction-panel');
        expect(panel).not.toHaveTextContent('What the agent thinks you are working on');
        expect(panel).toHaveTextContent('What the agent thinks it has done');
    });

    it('falls back to the timestamp prop when stats.when is missing', () => {
        const { when, ...stats } = baseStats;
        render(
            <CompactionChip
                stats={stats}
                summaryText="x"
                timestamp="2026-05-30T21:34:26.000000"
            />,
        );
        fireEvent.click(screen.getByTestId('compaction-chip'));
        // Should render *something* for "when" (not the em-dash placeholder).
        const panel = screen.getByTestId('compaction-panel');
        expect(panel.textContent).toMatch(/when/i);
        expect(panel.textContent).not.toMatch(/when\s*—/i);
    });
});
