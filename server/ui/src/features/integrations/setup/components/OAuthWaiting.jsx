import Button from '../../../../components/primitives/Button.jsx';
import Callout from '../../../../components/primitives/Callout.jsx';
import { ConnectionFrame } from './ConnectionLayout.jsx';
import styles from '../IntegrationSetupFlow.module.css';

export default function OAuthWaiting({ vendor, committing, authorizeUrl, onReopen, onExit, error }) {
    return (
        <ConnectionFrame title={`Connect ${vendor}`} description="Complete sign-in in the browser, then return here."
            footer={<>
                <Button variant="ghost" onClick={onExit} disabled={committing}>Exit setup</Button>
                {authorizeUrl && <Button variant="filled" onClick={onReopen} disabled={committing}>Reopen sign-in</Button>}
            </>}
        >
            <div className={styles.waiting}>
                <span className={styles.spinner} />
                <div><strong>{committing ? 'Finishing connection…' : 'Waiting for sign-in…'}</strong></div>
            </div>
            {!committing && authorizeUrl && <p>Window didn’t open? <a href={authorizeUrl} target="_blank" rel="noopener noreferrer">Open sign-in in a new tab</a>.</p>}
            {error && <Callout tone="warning" title="Checking sign-in" description={error.message} />}
        </ConnectionFrame>
    );
}
