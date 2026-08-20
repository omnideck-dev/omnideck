// State-mutation logic for a CLI integration's env-var list — add/update/
// remove a name-value row. Kept separate from the JSX that renders the rows
// so a future second form can reuse the logic without duplicating it.
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
