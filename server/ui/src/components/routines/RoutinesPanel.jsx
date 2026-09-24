import { StatusIcon, formatCron } from './routineUtils.jsx';
import styles from './RoutinesPanel.module.css';

export default function RoutinesPanel({ routines, runnerStatus, onSelectRoutine }) {
    return (
        <div className={styles.container}>
            {runnerStatus && (
                <div className={styles.runnerBar}>
                    <span className={styles.runnerLabel}>
                        Runner: {runnerStatus.paused ? 'paused' : runnerStatus.running ? 'active' : 'stopped'}
                    </span>
                    <span className={styles.runnerMeta}>
                        {runnerStatus.active_tasks}/{runnerStatus.max_concurrent} slots
                    </span>
                </div>
            )}
            {routines.length === 0 && (
                <div className={styles.empty}>
                    No routines yet. Ask the agent to create one.
                </div>
            )}
            <ul className={styles.list}>
                {routines.map(routine => (
                    <li
                        key={routine.id}
                        className={styles.item}
                        onClick={() => onSelectRoutine(routine.id)}
                    >
                        <div className={styles.itemHeader}>
                            <StatusIcon status={routine.status} size={12} />
                            <span className={styles.itemTitle}>{routine.description}</span>
                        </div>
                        <div className={styles.itemMeta}>
                            {routine.cron && <span className={styles.cron}>{formatCron(routine.cron)}{routine.timezone && <span className={styles.tz}> · {routine.timezone}</span>}</span>}
                            <span className={styles.status}>{routine.status}</span>
                        </div>
                    </li>
                ))}
            </ul>
        </div>
    );
}
