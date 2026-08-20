// Shared state-mutation logic for a CLI integration's env-var list, used by
// both the add wizard (CliSteps.jsx) and the detail pane's "Replace secret"
// form (IntegrationsTab.jsx). The two forms render these rows in visibly
// different contexts (different button primitives, CSS modules, and
// data-testid conventions), so only the update/add/remove logic — the part
// that would actually drift into subtly different bugs if duplicated — is
// shared here; each caller keeps its own JSX.
export function useCliVarsEditor(setVars) {
    const updateVar = (idx, field, value) => {
        setVars(vs => vs.map((v, i) => (i === idx ? { ...v, [field]: value } : v)));
    };
    const addVar = () => setVars(vs => [...vs, { name: '', value: '' }]);
    const removeVar = (idx) => setVars(vs => (
        vs.length > 1 ? vs.filter((_, i) => i !== idx) : vs
    ));
    return { updateVar, addVar, removeVar };
}
