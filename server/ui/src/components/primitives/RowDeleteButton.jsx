import ConfirmButton from './ConfirmButton.jsx';
import styles from './RowDeleteButton.module.css';

/**
 * Compact two-click delete for a table/list row: quiet by default, danger on
 * hover, "Confirm?" after the first click. Pair with SortableTable's
 * `revealOnHover` column so it only shows on row hover. The wrapper swallows
 * the click so deleting a row doesn't also open/select it.
 */
export default function RowDeleteButton({ onConfirm, title = 'Delete', 'data-testid': testid }) {
    return (
        <span className={styles.wrap} onClick={(e) => e.stopPropagation()}>
            <ConfirmButton
                icon="bi-trash3"
                confirmLabel="Confirm?"
                title={title}
                className={styles.btn}
                onConfirm={onConfirm}
                data-testid={testid}
            />
        </span>
    );
}
