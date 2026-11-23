import GoalDialog from './GoalDialog.jsx';

export default function GoalRequestDialog({ request, profileId, onCreated, onClose }) {
    if (!request) return null;
    return <GoalDialog
        key={request.conversationId}
        conversationId={request.conversationId}
        profileId={profileId}
        initialObjective={request.objective || ''}
        onCreated={onCreated}
        onStarted={() => request.onStarted?.()}
        onClose={() => {
            request.onClosed?.();
            onClose(request);
        }}
    />;
}
