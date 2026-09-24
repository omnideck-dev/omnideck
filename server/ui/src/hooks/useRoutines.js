import { useState, useEffect, useCallback, useRef } from 'react';

const POLL_INTERVAL = 5000;

/**
 * Routines state hook. Polls automatically whenever the routines panel is open
 * (panelOpen=true) or a routine is selected for detail view.
 */
export default function useRoutines(panelOpen) {
    const [routines, setRoutines] = useState([]);
    const [selectedRoutineId, setSelectedRoutineId] = useState(null);
    const _lastRoutinesJson = useRef('');

    // Reset selection each time the panel opens fresh.
    const prevOpen = useRef(false);
    useEffect(() => {
        if (panelOpen && !prevOpen.current) {
            setSelectedRoutineId(null);
        }
        prevOpen.current = panelOpen;
    }, [panelOpen]);

    // Poll while panel is open or a routine detail is showing.
    const shouldPoll = panelOpen || !!selectedRoutineId;
    useEffect(() => {
        if (!shouldPoll) return;
        let active = true;
        const poll = async () => {
            const [routinesRes, runnerRes] = await Promise.all([
                fetch('/api/routines').then(r => r.json()).catch(() => null),
                fetch('/api/runner/status').then(r => r.json()).catch(() => null),
            ]);
            if (!active) return;
            const runningIds = new Set(runnerRes?.running_routine_ids || []);
            if (routinesRes?.routines) {
                const enriched = routinesRes.routines.map(g => ({
                    ...g,
                    is_running: runningIds.has(g.id),
                }));
                const json = JSON.stringify(enriched);
                if (json !== _lastRoutinesJson.current) {
                    _lastRoutinesJson.current = json;
                    setRoutines(enriched);
                }
            }
        };
        poll();
        const id = setInterval(poll, POLL_INTERVAL);
        return () => { active = false; clearInterval(id); };
    }, [shouldPoll]);

    const fetchRoutineDetail = useCallback(async (routineId) => {
        const res = await fetch(`/api/routines/${routineId}`);
        return res.json();
    }, []);

    const deleteRoutine = useCallback(async (routineId) => {
        await fetch(`/api/routines/${routineId}`, { method: 'DELETE' });
        setRoutines(prev => prev.filter(g => g.id !== routineId));
        if (selectedRoutineId === routineId) setSelectedRoutineId(null);
    }, [selectedRoutineId]);

    const deleteRun = useCallback(async (routineId, runId) => {
        await fetch(`/api/routines/${routineId}/runs/${runId}`, { method: 'DELETE' });
    }, []);

    const pauseRoutine = useCallback(async (routineId) => {
        await fetch(`/api/routines/${routineId}/pause`, { method: 'POST' });
        setRoutines(prev => prev.map(g => g.id === routineId ? { ...g, status: 'paused' } : g));
    }, []);

    const resumeRoutine = useCallback(async (routineId) => {
        await fetch(`/api/routines/${routineId}/resume`, { method: 'POST' });
        setRoutines(prev => prev.map(g => g.id === routineId ? { ...g, status: 'active' } : g));
    }, []);

    const triggerRoutine = useCallback(async (routineId) => {
        const res = await fetch(`/api/routines/${routineId}/trigger`, { method: 'POST' });
        return res.json();
    }, []);

    return {
        routines,
        selectedRoutineId,
        setSelectedRoutineId,
        fetchRoutineDetail,
        deleteRoutine,
        deleteRun,
        pauseRoutine,
        resumeRoutine,
        triggerRoutine,
    };
}
