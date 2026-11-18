import styles from './SlashHint.module.css';

export function slashOptionId(id, index) {
    return `${id}-option-${index}`;
}

export default function SlashHint({ id, commands, activeIndex = 0, onPick }) {
    return <div id={id} className={styles.hint} role="listbox" aria-label="Commands" data-testid="slash-hint">
        {commands.map((item, index) => <div key={item.command} id={slashOptionId(id, index)}
            className={[styles.option, index === activeIndex && styles.active].filter(Boolean).join(' ')}
            role="option" aria-selected={index === activeIndex ? 'true' : undefined} tabIndex={-1}
            onMouseDown={(event) => event.preventDefault()} onClick={() => onPick(item.command)}>
            <span className={styles.command}>{item.command}</span>
            <span className={styles.description}>{item.description}</span>
            {index === activeIndex && <span className={styles.key} aria-hidden="true">Enter</span>}
        </div>)}
    </div>;
}
