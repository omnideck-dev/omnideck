import DesktopPreview from '../../components/DesktopPreview.jsx';

export default function GlobalOverlays({
    userDesktopOpen,
    closeUserDesktop,
}) {
    return (
        <>
            {userDesktopOpen && (
                <DesktopPreview visible onClose={closeUserDesktop} overlay />
            )}
        </>
    );
}
