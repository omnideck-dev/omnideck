import MarkdownContent from '../../components/MarkdownContent.jsx';
import styles from './GoalAnswerQuote.module.css';

export default function GoalAnswerQuote({ item }) {
    return <div className={styles.answer} data-testid="goal-question-answer">
        <div className={styles.question}>
            <span aria-hidden="true">↳ </span>{item.question}
        </div>
        <MarkdownContent>{item.answer}</MarkdownContent>
    </div>;
}
