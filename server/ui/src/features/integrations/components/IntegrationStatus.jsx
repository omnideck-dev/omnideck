import ConnectionStatus from '../../../components/ConnectionStatus.jsx';

const STATUS_VIEW = {
    auth_failed: 'auth failed',
    broken: 'not running',
};

export default function IntegrationStatus({ state }) {
    if (state === 'running') {
        return (
            <ConnectionStatus data-testid="integration-status">Connected</ConnectionStatus>
        );
    }
    // Unknown runtime states fail closed visually; never label an unfamiliar
    // supervisor state as connected.
    return (
        <ConnectionStatus tone="danger" data-testid="integration-status">
            {STATUS_VIEW[state] || STATUS_VIEW.broken}
        </ConnectionStatus>
    );
}
