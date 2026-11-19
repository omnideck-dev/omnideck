import { useEffect } from 'react';

import { subscribeActivityStream } from './activityStream.js';
import { useAppEffectDispatch } from './AppEffects.jsx';

export default function ActivityStreamProvider({ children }) {
    const dispatch = useAppEffectDispatch();
    useEffect(() => subscribeActivityStream(dispatch), [dispatch]);
    return children;
}
