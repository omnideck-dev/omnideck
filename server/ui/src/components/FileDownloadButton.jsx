import DownloadIcon from './icons/DownloadIcon.jsx';
import IconButton from './primitives/IconButton.jsx';

export default function FileDownloadButton({ download }) {
    return (
        <IconButton
            size="sm"
            onClick={(e) => { e.stopPropagation(); download(); }}
            title="Download"
            aria-label="Download file"
            data-testid="file-download"
        >
            <DownloadIcon size={14} />
        </IconButton>
    );
}
