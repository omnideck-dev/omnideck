import FilePreview from '../../components/FilePreview.jsx';
import IconButton from '../../components/primitives/IconButton.jsx';
import PhoneHeader from './PhoneHeader.jsx';
import styles from './PhoneFileScreen.module.css';

export default function PhoneFileScreen({ item, backLabel, onBack, onOpenConversation }) {
    return (
        <div className={styles.screen} data-testid="phone-file">
            <PhoneHeader
                onBack={onBack}
                backLabel={backLabel}
                title={item.filename || 'File'}
                actions={onOpenConversation && (
                    <IconButton
                        size="lg"
                        onClick={onOpenConversation}
                        title="Open source conversation"
                        aria-label="Open source conversation"
                        data-testid="phone-file-open-conversation"
                    >
                        <i className="bi bi-chat-left-text" aria-hidden="true" />
                    </IconButton>
                )}
            />
            <div className={styles.preview}>
                <FilePreview item={item} />
            </div>
        </div>
    );
}
