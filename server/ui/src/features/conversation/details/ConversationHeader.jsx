import ConversationDetails from './ConversationDetails.jsx';
import styles from '../../../components/ChatPanel.module.css';

export default function ConversationHeader({ title, conversationId, model, onSelect }) {
    return <header className={styles.titleBar} data-testid="chat-title-bar">
        <span className={styles.title} data-testid="chat-title">{title}</span>
        <ConversationDetails key={conversationId || 'draft'} conversationId={conversationId} model={model} onSelect={onSelect} />
    </header>;
}
