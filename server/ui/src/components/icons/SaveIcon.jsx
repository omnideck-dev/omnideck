export default function SaveIcon({ size = 14, className }) {
    return (
        <svg
            width={size}
            height={size}
            viewBox="0 0 16 16"
            fill="none"
            xmlns="http://www.w3.org/2000/svg"
            className={className}
            aria-hidden="true"
        >
            <path
                d="M2.5 2.5h8L13.5 5.5v8h-11v-11z"
                stroke="currentColor"
                strokeWidth="1.2"
                strokeLinejoin="round"
            />
            <path
                d="M5 2.5v3h5v-3M5 13.5V9h6v4.5"
                stroke="currentColor"
                strokeWidth="1.2"
                strokeLinejoin="round"
            />
        </svg>
    );
}
