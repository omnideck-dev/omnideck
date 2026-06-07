import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import MarkdownContent from '../MarkdownContent.jsx';

describe('MarkdownContent links', () => {
  it('opens rendered links in a new tab with a safe rel', () => {
    render(<MarkdownContent>{'[example](https://example.com)'}</MarkdownContent>);
    const link = screen.getByRole('link', { name: 'example' });
    expect(link).toHaveAttribute('href', 'https://example.com');
    expect(link).toHaveAttribute('target', '_blank');
    expect(link).toHaveAttribute('rel', 'noopener noreferrer');
  });
});
