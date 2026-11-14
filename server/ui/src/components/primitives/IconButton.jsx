import { forwardRef } from 'react';
import styles from './IconButton.module.css';

const IconButton = forwardRef(function IconButton({
    size = 'sm',
    className,
    children,
    ...rest
}, ref) {
    const cls = [styles.btn, styles[size], className].filter(Boolean).join(' ');
    return (
        <button ref={ref} type="button" className={cls} {...rest}>
            {children}
        </button>
    );
});

export default IconButton;
