import { useEffect, useRef } from 'react';
import styles from './SplitHandle.module.css';

/**
 * A draggable vertical divider between two sibling tab groups.
 *
 * @param {Object} props
 * @param {function(number): void} props.onDrag - Callback that receives the new split percentage (20-80)
 * @param {function(number): void} props.onDragEnd - Callback that commits the final percentage
 * @returns {JSX.Element}
 */
export default function SplitHandle({
    onDrag,
    onDragEnd,
    className = '',
}) {
    const handleRef = useRef(null);
    const onDragRef = useRef(onDrag);
    const onDragEndRef = useRef(onDragEnd);
    onDragRef.current = onDrag;
    onDragEndRef.current = onDragEnd;

    useEffect(() => {
        const el = handleRef.current;
        if (!el) return;

        let dragging = false;
        let latestRatio = null;

        // Transparent overlay prevents iframes from stealing mouse events during drag
        let overlay = null;

        const onMouseMove = (e) => {
            if (!dragging) return;
            const parent = el.parentElement;
            if (!parent) return;
            const rect = parent.getBoundingClientRect();
            const pct = ((e.clientX - rect.left) / rect.width) * 100;
            latestRatio = Math.max(20, Math.min(80, pct));
            onDragRef.current(latestRatio);
        };

        const onMouseUp = () => {
            if (!dragging) return;
            dragging = false;
            document.body.style.userSelect = '';
            el.classList.remove(styles.dragging);
            if (overlay) { overlay.remove(); overlay = null; }
            document.removeEventListener('mousemove', onMouseMove);
            document.removeEventListener('mouseup', onMouseUp);
            if (latestRatio !== null) {
                onDragEndRef.current?.(latestRatio);
            }
            latestRatio = null;
        };

        const onMouseDown = (e) => {
            e.preventDefault();
            dragging = true;
            latestRatio = null;
            document.body.style.userSelect = 'none';
            el.classList.add(styles.dragging);
            overlay = document.createElement('div');
            overlay.style.cssText = 'position:fixed;inset:0;z-index:9999;cursor:col-resize;';
            document.body.appendChild(overlay);
            document.addEventListener('mousemove', onMouseMove);
            document.addEventListener('mouseup', onMouseUp);
        };

        el.addEventListener('mousedown', onMouseDown);

        return () => {
            el.removeEventListener('mousedown', onMouseDown);
            if (dragging) {
                document.body.style.userSelect = '';
                if (overlay) { overlay.remove(); overlay = null; }
                document.removeEventListener('mousemove', onMouseMove);
                document.removeEventListener('mouseup', onMouseUp);
            }
        };
    }, []);

    return (
        <div
            ref={handleRef}
            className={`${styles.splitHandle} ${className}`.trim()}
            role="separator"
            aria-orientation="vertical"
            aria-label="Resize tab groups"
        />
    );
}
