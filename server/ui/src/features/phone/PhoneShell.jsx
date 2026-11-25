import { useCallback, useEffect, useLayoutEffect, useState } from 'react';

import { label as conversationLabel } from '../../components/conversationSections.js';
import { FileControlsProvider } from '../../components/FileControls.jsx';
import { useConversationCatalog } from '../conversation/catalog/ConversationCatalog.jsx';
import {
    useActiveConversationId,
    useConversationSessionCommands,
} from '../conversation/session/ConversationSession.jsx';
import PhoneArtifactsScreen from './PhoneArtifactsScreen.jsx';
import PhoneChatScreen from './PhoneChatScreen.jsx';
import PhoneConversationList from './PhoneConversationList.jsx';
import PhoneFileScreen from './PhoneFileScreen.jsx';
import { PHONE_FILE_CONTROLS } from './phoneFileControls.js';
import styles from './PhoneShell.module.css';

const LIST = { screen: 'list' };
const BACK_LABELS = { list: 'Chats', chat: 'Chat', artifacts: 'Artifacts' };

export default function PhoneShell() {
    const activeConversationId = useActiveConversationId();
    const { loadConversation, newConversation, refreshActiveConversation } = useConversationSessionCommands();
    const { items, setVisibleConversation } = useConversationCatalog();
    const [stack, setStack] = useState([LIST]);
    const top = stack[stack.length - 1];

    const push = useCallback((entry) => setStack((prev) => [...prev, entry]), []);
    const back = useCallback(() => setStack((prev) => (prev.length > 1 ? prev.slice(0, -1) : prev)), []);
    const replaceTop = useCallback((entry) => setStack((prev) => [...prev.slice(0, -1), entry]), []);

    const openConversation = useCallback(async (conversationId) => {
        if (conversationId !== activeConversationId) {
            const loaded = await loadConversation(conversationId);
            if (!loaded) return;
        }
        setStack([LIST, { screen: 'chat' }]);
    }, [activeConversationId, loadConversation]);

    const startChat = useCallback(async () => {
        await newConversation();
        setStack([LIST, { screen: 'chat' }]);
    }, [newConversation]);

    const resetConversation = useCallback(() => { void newConversation(); }, [newConversation]);

    const openArtifacts = useCallback((conversationId = null) => {
        push({ screen: 'artifacts', conversationId });
    }, [push]);

    const openFile = useCallback((item, sourceConversationId = null) => {
        push({ screen: 'file', item, sourceConversationId });
    }, [push]);

    const chatVisible = top.screen === 'chat';
    useLayoutEffect(() => {
        setVisibleConversation(chatVisible ? activeConversationId : null);
    }, [setVisibleConversation, chatVisible, activeConversationId]);
    useLayoutEffect(() => () => setVisibleConversation(null), [setVisibleConversation]);

    useEffect(() => {
        const onVisible = () => {
            if (document.visibilityState === 'visible') void refreshActiveConversation();
        };
        document.addEventListener('visibilitychange', onVisible);
        return () => document.removeEventListener('visibilitychange', onVisible);
    }, [refreshActiveConversation]);

    const titleFor = (conversationId) => {
        const listed = items.find((item) => item.conversation_id === conversationId);
        return listed ? conversationLabel(listed) : 'This chat';
    };

    const renderScreen = (entry, index) => {
        const backLabel = index > 0 ? BACK_LABELS[stack[index - 1].screen] : undefined;
        if (entry.screen === 'list') {
            return (
                <PhoneConversationList
                    activeConversationId={activeConversationId}
                    onOpenConversation={openConversation}
                    onStartChat={startChat}
                    onResetConversation={resetConversation}
                    onOpenArtifacts={() => openArtifacts()}
                />
            );
        }
        if (entry.screen === 'chat') {
            return (
                <PhoneChatScreen
                    onBack={back}
                    onPreview={(item) => openFile(item)}
                    onOpenArtifacts={openArtifacts}
                />
            );
        }
        if (entry.screen === 'artifacts') {
            return (
                <PhoneArtifactsScreen
                    conversationId={entry.conversationId}
                    conversationTitle={entry.conversationId ? titleFor(entry.conversationId) : ''}
                    backLabel={backLabel}
                    onBack={back}
                    onClearConversation={() => replaceTop({ screen: 'artifacts', conversationId: null })}
                    onOpenArtifact={(artifact) => openFile(
                        artifact,
                        entry.conversationId ? null : artifact.conversation_id,
                    )}
                />
            );
        }
        return (
            <PhoneFileScreen
                item={entry.item}
                backLabel={backLabel}
                onBack={back}
                onOpenConversation={entry.sourceConversationId
                    ? () => openConversation(entry.sourceConversationId)
                    : undefined}
            />
        );
    };

    return (
        <FileControlsProvider controls={PHONE_FILE_CONTROLS}>
            <div className={styles.shell} data-testid="phone-app">
                {stack.map((entry, index) => (
                    <div
                        key={`${index}:${entry.screen}`}
                        className={styles.screen}
                        hidden={index !== stack.length - 1}
                    >
                        {renderScreen(entry, index)}
                    </div>
                ))}
            </div>
        </FileControlsProvider>
    );
}
