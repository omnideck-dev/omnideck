import Button from '../../components/primitives/Button.jsx';

/** Renders the toolbar subset of a view's shared command model. */
export default function DesktopViewActionBar({ actions, placement }) {
    return actions
        .filter((action) => action.placements.includes(placement))
        .map((action) => (
            <Button
                key={action.id}
                variant="ghost"
                onClick={action.execute}
                disabled={action.disabled}
                title={action.ariaLabel}
                aria-label={action.ariaLabel}
                data-testid={action.testid}
            >
                <i className={`bi ${action.icon}`} />
            </Button>
        ));
}
