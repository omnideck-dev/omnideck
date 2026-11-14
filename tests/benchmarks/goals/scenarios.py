"""Frozen task descriptions; grading requirements are never given to the model."""
from dataclasses import dataclass

VERSION = 'goal-following-v1'


@dataclass(frozen=True)
class Scenario:
    id: str
    family: str
    objective: str
    answers: tuple[str, ...] = ()
    ongoing: bool = False
    max_runs: int = 8
    horizon_hours: int = 72


SCENARIOS = (
    Scenario('verified_delivery', 'completion', 'Send the neighborhood newsletter announcement to the library and confirm delivery. Send it only once.'),
    Scenario('revise_approach', 'planning', 'Arrange distribution of our newsletter through a local organization. Find an available partner and confirm delivery of the announcement. Do not send duplicate requests.'),
    Scenario('blocking_question', 'questions', 'Book a dental appointment covered by my insurance. I have not told you my insurance plan yet. Any available afternoon works. You may book once coverage is confirmed.', ('My insurance is Cedar Dental.',)),
    Scenario('partial_answers', 'questions', 'Book a dental appointment covered by my insurance, at my preferred time. You do not know my insurance or preferred time yet. Research available offices while waiting for those details; do not book until both are known.', ('I can confirm only my insurance so far: Cedar Dental.', 'My preferred time is Tuesday afternoon. My insurance is Cedar Dental.')),
    Scenario('corrected_answer', 'questions', 'Run one community newsletter campaign within my latest budget, then check its results and report the verified outcome. My budget answers are in the saved goal questions.'),
    Scenario('external_edit', 'direction', 'Arrange newsletter distribution through a local organization and confirm delivery. You may contact an available organization.'),
    Scenario('scheduled_return', 'scheduling', 'Send the newsletter announcement to the library, then confirm delivery. Their delivery report will not be available until tomorrow. Do not send duplicate requests.'),
    Scenario('history_recall', 'memory', 'Confirm delivery of the library announcement sent in an earlier run. The receipt was recorded in older goal progress. Do not send another announcement.'),
    Scenario('interrupted_action', 'recovery', 'Send the newsletter announcement to the library and confirm delivery. An interrupted request may have succeeded; check its status before repeating it.'),
    Scenario('compaction', 'memory', 'Send the newsletter announcement to the library and confirm delivery. Preserve the receipt and verified outcome for future reference. Send only once.'),
    Scenario('pause_cancel', 'direction', 'Arrange newsletter distribution through the library. You may contact them and check delivery.'),
    Scenario('ongoing_campaign', 'ongoing', 'Keep growing the neighborhood newsletter through daily community campaigns. Check results when available and adapt the next campaign to the evidence. Use free channels only. Keep working until I pause or cancel.', ongoing=True, horizon_hours=192),
)


def scenario_by_id(identifier):
    return next(s for s in SCENARIOS if s.id == identifier)
