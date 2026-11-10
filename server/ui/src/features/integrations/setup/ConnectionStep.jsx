import Button from '../../../components/primitives/Button.jsx';
import Callout from '../../../components/primitives/Callout.jsx';
import { getConnectionAdapter } from '../catalog/adapterRegistry.js';
import AppPasswordConnection from './connection-adapters/AppPasswordConnection.jsx';
import GoogleOAuthConnection from './connection-adapters/GoogleOAuthConnection.jsx';
import HttpTokenConnection from './connection-adapters/HttpTokenConnection.jsx';
import TestConnection from './connection-adapters/TestConnection.jsx';
import MCPOAuthConnection from './connection-adapters/MCPOAuthConnection.jsx';
import SlackOAuthConnection from './connection-adapters/SlackOAuthConnection.jsx';
import styles from './IntegrationSetupFlow.module.css';

// The catalog selects a stable adapter kind; it never describes or renders the
// form itself. Each adapter remains an explicit frontend component while the
// surrounding setup flow, field layout, actions, and submission lifecycle are
// shared.
const CONNECTION_COMPONENTS = {
    app_password: AppPasswordConnection,
    google_oauth: GoogleOAuthConnection,
    http_token: HttpTokenConnection,
    test: TestConnection,
    mcp_oauth: MCPOAuthConnection,
    slack_oauth: SlackOAuthConnection,
};

export default function ConnectionStep(props) {
    if (!props.entry) {
        return (
            <div className={styles.stepPage}>
                <div className={styles.modalBody}>
                    <Callout
                        tone="warning"
                        title="Connection setup isn't available"
                        description="This integration is no longer present in the catalog."
                    />
                </div>
                <div className={styles.stepFooter}>
                    <Button onClick={props.onBack}><i className="bi bi-arrow-left" /> Back</Button>
                </div>
            </div>
        );
    }
    const adapter = getConnectionAdapter(props.entry.id);
    const ConnectionComponent = CONNECTION_COMPONENTS[adapter.kind];

    if (ConnectionComponent) return <ConnectionComponent {...props} />;

    return (
        <div className={styles.stepPage}>
            <div className={styles.modalBody}>
                <Callout
                    tone="warning"
                    title="Connection setup isn't available"
                    description={`This build does not have a setup adapter for ${props.entry.title}.`}
                />
            </div>
            <div className={styles.stepFooter}>
                <Button onClick={props.onBack}><i className="bi bi-arrow-left" /> Back</Button>
            </div>
        </div>
    );
}
