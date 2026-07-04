import styles from './StarterPrompts.module.css';

const DEFAULT_PROMPTS = [
    {
        icon: 'bi-search',
        title: 'Research a topic',
        text: 'Do a deep research on the latest developments in large language models',
    },
    {
        icon: 'bi-code-slash',
        title: 'Write some code',
        text: 'Write an HTML snake game',
    },
    {
        icon: 'bi-globe2',
        title: 'Browse the web',
        text: 'Go to wikipedia.org and summarize the featured article of the day',
    },
    {
        icon: 'bi-bullseye',
        title: 'Create a routine',
        text: 'Help me create a routine and break it down into actionable steps',
    },
];

/**
 * Grid of clickable suggestion cards. Each card hands its prompt text to
 * onSelect — used both by the empty chat (default prompts) and the empty
 * routines view (routine-shaped prompts), so the two empty states look the same.
 */
export default function StarterPrompts({
    onSelect,
    prompts = DEFAULT_PROMPTS,
    heading = 'What can I help you with?',
    subheading,
}) {
    return (
        <div className={styles.container}>
            <div className={styles.intro}>
                <h2 className={styles.heading}>{heading}</h2>
                {subheading && <p className={styles.subheading}>{subheading}</p>}
            </div>
            <div className={styles.grid}>
                {prompts.map((prompt) => (
                    <button
                        key={prompt.title}
                        className={styles.card}
                        onClick={() => onSelect(prompt.text)}
                        data-testid="starter-prompt"
                    >
                        <span className={styles.icon}><i className={prompt.icon} /></span>
                        <span className={styles.title}>{prompt.title}</span>
                        <span className={styles.text}>{prompt.text}</span>
                    </button>
                ))}
            </div>
        </div>
    );
}
