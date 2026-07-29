import {
    useCallback,
    useEffect,
    useRef,
    useState,
} from 'react';

export const SIDEBAR_DRAG_THRESHOLD = 4;

function sameOrder(left, right) {
    return left.length === right.length
        && left.every((id, index) => id === right[index]);
}

function movedOrder(ids, movingId, targetIndex) {
    const withoutMoving = ids.filter((id) => id !== movingId);
    const insertionIndex = Math.max(0, Math.min(targetIndex, withoutMoving.length));
    withoutMoving.splice(insertionIndex, 0, movingId);
    return withoutMoving;
}

/**
 * Reorders one vertical sidebar group without turning small pointer movement
 * into a drag. Each hook instance owns one hard boundary, so a row can never
 * cross from destinations into Apps or vice versa.
 */
export default function useSidebarReorder({ ids, onReorder }) {
    const containerRef = useRef(null);
    const itemElementsRef = useRef(new Map());
    const idsRef = useRef(ids);
    const onReorderRef = useRef(onReorder);
    const dragRef = useRef(null);
    const suppressedClickRef = useRef(null);
    const userSelectRef = useRef('');
    const [draggingId, setDraggingId] = useState(null);
    const [announcement, setAnnouncement] = useState('');

    idsRef.current = ids;
    onReorderRef.current = onReorder;

    const registerItem = useCallback((id, element) => {
        if (element) itemElementsRef.current.set(id, element);
        else itemElementsRef.current.delete(id);
    }, []);

    const applyOrder = useCallback((nextIds) => {
        if (sameOrder(nextIds, idsRef.current)) return false;
        idsRef.current = nextIds;
        onReorderRef.current(nextIds);
        return true;
    }, []);

    const announcePosition = useCallback((label, orderedIds) => {
        const position = orderedIds.indexOf(label.id) + 1;
        setAnnouncement(
            `${label.text} moved to position ${position} of ${orderedIds.length}`,
        );
    }, []);

    const moveItem = useCallback((id, delta, text) => {
        const currentIds = idsRef.current;
        const currentIndex = currentIds.indexOf(id);
        if (currentIndex < 0) return false;
        const targetIndex = Math.max(
            0,
            Math.min(currentIndex + delta, currentIds.length - 1),
        );
        if (targetIndex === currentIndex) return false;
        const nextIds = [...currentIds];
        nextIds.splice(currentIndex, 1);
        nextIds.splice(targetIndex, 0, id);
        applyOrder(nextIds);
        announcePosition({ id, text }, nextIds);
        return true;
    }, [announcePosition, applyOrder]);

    const onItemKeyDown = useCallback((id, text, event) => {
        if (!event.altKey || (event.key !== 'ArrowUp' && event.key !== 'ArrowDown')) {
            return;
        }
        event.preventDefault();
        moveItem(id, event.key === 'ArrowUp' ? -1 : 1, text);
    }, [moveItem]);

    const onItemPointerDown = useCallback((id, text, event) => {
        if (event.button !== 0 || dragRef.current) return;
        dragRef.current = {
            id,
            text,
            pointerId: event.pointerId,
            startX: event.clientX,
            startY: event.clientY,
            originalIds: [...idsRef.current],
            started: false,
        };
        event.currentTarget.setPointerCapture?.(event.pointerId);
    }, []);

    const consumeClick = useCallback((id, event) => {
        if (suppressedClickRef.current !== id) return false;
        suppressedClickRef.current = null;
        event.preventDefault();
        event.stopPropagation();
        return true;
    }, []);

    useEffect(() => {
        const onPointerMove = (event) => {
            const drag = dragRef.current;
            if (!drag || event.pointerId !== drag.pointerId) return;
            const distance = Math.hypot(
                event.clientX - drag.startX,
                event.clientY - drag.startY,
            );
            if (!drag.started && distance < SIDEBAR_DRAG_THRESHOLD) return;

            if (!drag.started) {
                drag.started = true;
                userSelectRef.current = document.body.style.userSelect;
                document.body.style.userSelect = 'none';
                setDraggingId(drag.id);
            }
            event.preventDefault();

            const currentIds = idsRef.current;
            const otherIds = currentIds.filter((id) => id !== drag.id);
            let insertionIndex = otherIds.length;
            for (let index = 0; index < otherIds.length; index += 1) {
                const element = itemElementsRef.current.get(otherIds[index]);
                if (!element) continue;
                const rect = element.getBoundingClientRect();
                if (event.clientY < rect.top + (rect.height / 2)) {
                    insertionIndex = index;
                    break;
                }
            }
            applyOrder(movedOrder(currentIds, drag.id, insertionIndex));
        };

        const finishPointer = (event, cancelled = false) => {
            const drag = dragRef.current;
            if (!drag || event.pointerId !== drag.pointerId) return;
            dragRef.current = null;
            if (!drag.started) return;

            document.body.style.userSelect = userSelectRef.current;
            setDraggingId(null);
            if (cancelled) {
                applyOrder(drag.originalIds);
                return;
            }

            const finalIds = idsRef.current;
            if (!sameOrder(finalIds, drag.originalIds)) {
                suppressedClickRef.current = drag.id;
                window.setTimeout(() => {
                    if (suppressedClickRef.current === drag.id) {
                        suppressedClickRef.current = null;
                    }
                }, 0);
                announcePosition(
                    { id: drag.id, text: drag.text },
                    finalIds,
                );
            }
        };

        const onPointerUp = (event) => finishPointer(event);
        const onPointerCancel = (event) => finishPointer(event, true);
        document.addEventListener('pointermove', onPointerMove, { passive: false });
        document.addEventListener('pointerup', onPointerUp);
        document.addEventListener('pointercancel', onPointerCancel);
        return () => {
            document.removeEventListener('pointermove', onPointerMove);
            document.removeEventListener('pointerup', onPointerUp);
            document.removeEventListener('pointercancel', onPointerCancel);
            document.body.style.userSelect = userSelectRef.current;
        };
    }, [announcePosition, applyOrder]);

    return {
        announcement,
        consumeClick,
        containerRef,
        draggingId,
        moveItem,
        onItemKeyDown,
        onItemPointerDown,
        registerItem,
    };
}
