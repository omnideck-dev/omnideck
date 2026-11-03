import Button from './primitives/Button.jsx';

export default function SavedThinkingStatus({ loading, error, retry }) {
    if (loading) return <span role="status">Loading thinking…</span>;
    if (error) return (
        <span role="alert">
            Couldn’t load thinking.{' '}
            <Button variant="ghost" onClick={retry}>Retry</Button>
        </span>
    );
    return null;
}
