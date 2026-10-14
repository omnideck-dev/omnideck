import styles from './ListItem.module.css';

/**
 * Per-row list item with the canonical SIGNAL styling:
 * Rounded object boundary, accent outline and muted background on selection.
 *
 * Use `name` / `description` / `badges` for the common list-row pattern,
 * or pass `children` for custom content layouts.
 *
 * @param {Object} props
 * @param {boolean} [props.active]
 * @param {function} [props.onClick]
 * @param {React.ReactNode} [props.name]
 * @param {React.ReactNode} [props.description]
 * @param {React.ReactNode} [props.badges]
 * @param {React.ReactNode} [props.icon] - optional leading icon
 * @param {React.ReactNode} [props.children] - overrides name/description/badges when provided
 * @param {string} [props.className]
 */
export default function ListItem({
    active = false,
    onClick,
    name,
    description,
    badges,
    icon,
    children,
    className = '',
    ...rest
}) {
    const classes = [styles.item, active ? styles.active : '', className]
        .filter(Boolean)
        .join(' ');
    return (
        <button type="button" className={classes} onClick={onClick} {...rest}>
            {icon && <span className={styles.icon} aria-hidden="true">{icon}</span>}
            {children ?? (
                <div className={styles.body}>
                    {name && <span className={styles.name}>{name}</span>}
                    {description && <span className={styles.description}>{description}</span>}
                    {badges && <div className={styles.badges}>{badges}</div>}
                </div>
            )}
        </button>
    );
}
