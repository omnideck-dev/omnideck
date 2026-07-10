import { useCallback, useEffect, useState } from 'react';

/**
 * Editable skills hook. Fetches skill records on mount and provides create,
 * update, and delete over /api/skills. Records are keyed by their stable `id`;
 * `name` is the editable display field.
 */
export default function useSkills() {
    const [skills, setSkills] = useState([]);
    const [loading, setLoading] = useState(true);

    const refresh = useCallback(async () => {
        setLoading(true);
        try {
            const res = await fetch('/api/skills');
            const data = await res.json();
            setSkills(Array.isArray(data) ? data : []);
        } catch {
            // keep current state on error
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => { refresh(); }, [refresh]);

    const createSkill = useCallback(async (skill) => {
        const res = await fetch('/api/skills', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(skill),
        });
        const body = await res.json();
        if (!res.ok) return { ok: false, error: body };
        setSkills((prev) => [...prev, body]);
        return { ok: true, data: body };
    }, []);

    const updateSkill = useCallback(async (id, skill) => {
        const res = await fetch(`/api/skills/${encodeURIComponent(id)}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(skill),
        });
        const body = await res.json();
        if (!res.ok) return { ok: false, error: body };
        setSkills((prev) => prev.map((s) => (s.id === id ? body : s)));
        return { ok: true, data: body };
    }, []);

    const deleteSkill = useCallback(async (id) => {
        const res = await fetch(`/api/skills/${encodeURIComponent(id)}`, { method: 'DELETE' });
        if (res.ok) setSkills((prev) => prev.filter((s) => s.id !== id));
        return { ok: res.ok };
    }, []);

    // Add skills the server already created (e.g. from a pack import) without a
    // refetch.
    const addSkills = useCallback((records) => {
        if (!records?.length) return;
        setSkills((prev) => [...prev, ...records]);
    }, []);

    return { skills, loading, refresh, createSkill, updateSkill, deleteSkill, addSkills };
}
