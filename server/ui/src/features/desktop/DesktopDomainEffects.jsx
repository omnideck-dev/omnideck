import { memo } from 'react';

import {
    ArtifactDesktopEffects,
} from '../artifacts/ArtifactDesktopAdapter.jsx';
import {
    CustomAppDesktopEffects,
} from '../customApps/CustomAppDesktopAdapter.jsx';
import {
    WorkspaceResourceDesktopEffects,
} from '../workspace/WorkspaceResourceDesktopAdapter.jsx';

/**
 * Explicit composition point for feature effects that react to Desktop events.
 *
 * These components render nothing and do not wrap Desktop content. Keeping the
 * list here makes application-level feature installation visible while each
 * feature retains its own lifecycle policy.
 */
function DesktopDomainEffects() {
    return (
        <>
            <WorkspaceResourceDesktopEffects />
            <CustomAppDesktopEffects />
            <ArtifactDesktopEffects />
        </>
    );
}

// Layout renders update frequently; the installed feature effects should wake
// only when one of the narrow contexts they consume actually changes.
export default memo(DesktopDomainEffects);
