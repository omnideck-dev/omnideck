import {
    createContext,
    useCallback,
    useContext,
    useEffect,
    useRef,
} from 'react';

const AppEffectDispatchContext = createContext(null);
const AppEffectSubscriptionContext = createContext(null);

/**
 * Delivers typed, one-time application effects without turning them into
 * globally retained state. Feature owners subscribe and decide whether an
 * effect should update React state, invalidate data, or perform an operation.
 */
export function AppEffectsProvider({ children }) {
    const subscribersRef = useRef(new Map());

    const dispatchAppEffect = useCallback(
        /** @param {import('./appEffects.types').AppEffect} effect */
        (effect) => {
            if (!effect?.type) return;
            const subscribers = subscribersRef.current.get(effect.type);
            if (!subscribers) return;

            // Snapshot the set so handlers may subscribe or unsubscribe safely
            // without changing delivery of the current effect.
            for (const subscriber of [...subscribers]) {
                try {
                    subscriber(effect);
                } catch {
                    // One feature failing to handle an effect must not prevent
                    // the remaining feature owners from seeing it.
                }
            }
        },
        [],
    );

    const subscribe = useCallback((type, subscriber) => {
        let subscribers = subscribersRef.current.get(type);
        if (!subscribers) {
            subscribers = new Set();
            subscribersRef.current.set(type, subscribers);
        }
        subscribers.add(subscriber);

        return () => {
            subscribers.delete(subscriber);
            if (subscribers.size === 0) subscribersRef.current.delete(type);
        };
    }, []);

    return (
        <AppEffectDispatchContext.Provider value={dispatchAppEffect}>
            <AppEffectSubscriptionContext.Provider value={subscribe}>
                {children}
            </AppEffectSubscriptionContext.Provider>
        </AppEffectDispatchContext.Provider>
    );
}

export function useAppEffectDispatch() {
    const dispatch = useContext(AppEffectDispatchContext);
    if (dispatch === null) {
        throw new Error('useAppEffectDispatch must be used within AppEffectsProvider');
    }
    return dispatch;
}

/**
 * Subscribe a feature owner to one application effect type.
 *
 * @template {import('./appEffects.types').AppEffectType} Type
 * @param {Type} type
 * @param {(effect: import('./appEffects.types').AppEffectOfType<Type>) => void} handler
 */
export function useAppEffectSubscription(type, handler) {
    const subscribe = useContext(AppEffectSubscriptionContext);
    if (subscribe === null) {
        throw new Error('useAppEffectSubscription must be used within AppEffectsProvider');
    }

    useEffect(() => subscribe(type, handler), [handler, subscribe, type]);
}
