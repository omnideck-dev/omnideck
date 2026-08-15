import DesktopPreview from '../../components/DesktopPreview.jsx';
import SoftwareUpdateNotice from '../../components/SoftwareUpdateNotice.jsx';

export default function GlobalOverlays({
    userDesktopOpen,
    closeUserDesktop,
}) {
    return (
        <>
            {userDesktopOpen && (
                <DesktopPreview visible onClose={closeUserDesktop} overlay />
            )}
            <SoftwareUpdateNotice />
        </>
    );
}
