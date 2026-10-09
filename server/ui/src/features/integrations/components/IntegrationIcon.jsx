import { getConnectionAdapter } from '../catalog/adapterRegistry.js';

export default function IntegrationIcon({ catalogId, className = '' }) {
    const adapter = getConnectionAdapter(catalogId);
    return (
        <span className={className} aria-hidden="true">
            <i className={`bi ${adapter.icon}`} />
        </span>
    );
}
