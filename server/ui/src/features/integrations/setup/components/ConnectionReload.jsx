import Button from '../../../../components/primitives/Button.jsx';
import { ConnectionFrame } from './ConnectionLayout.jsx';

/** Authorization is complete; only loading the saved connection may be retried. */
export default function ConnectionReload({ busy, onRetry, onExit }) {
    return (
        <ConnectionFrame
            title="Sign-in complete"
            description={busy
                ? 'Loading your saved connection…'
                : 'Your connection was saved. Try loading it again to continue—no need to sign in again.'}
            footer={<>
                <Button variant="ghost" onClick={onExit} disabled={busy}>Exit setup</Button>
                <Button variant="filled" onClick={onRetry} disabled={busy} loading={busy}>
                    Retry loading connection
                </Button>
            </>}
        />
    );
}
