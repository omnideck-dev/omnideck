"""Real runtime and scheduler with isolated persistence, clock and service I/O."""
import asyncio
import importlib
import json
import time
from contextlib import ExitStack, asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from agent_core.control import StopRequestedError
from agent_core.providers import ChatResponse
from agent_core.tools._callable_schema import callable_to_json_schema
from agent_runtime import AgentRuntime, AgentRunRequest
from agents import AgentProfile
from agents._agent_profiles import save_agent_profile
from config import load_config
from conversations import load_events_jsonl
from goals import GoalAnswerRecorder, GoalStore, GoalStep, GoalQuestionChange, GoalAnswerSubmission, answer_message
from goals._scheduling import GoalWorkSource
from scheduling import Scheduler
from providers import _provider_class, get_provider
from agent_core.providers import LLMConfig
from skills._store import SkillRecord, save_skill_record
from skills._tool_categories import ToolCategory

from .world import Clock, World


class RecordedProvider:
    def __init__(self, provider, harness, path, max_calls):
        self.provider, self.harness, self.path, self.max_calls = provider, harness, path, max_calls
        self.calls = 0
        self.usage = {'prompt_tokens': 0, 'completion_tokens': 0}
        self.cache = {'cache_read_tokens': None, 'cache_creation_tokens': None}
        self.transport_errors = []

    def before(self, kwargs, streaming):
        if self.harness.crash_pending:
            raise StopRequestedError()
        if self.calls >= self.max_calls:
            self.harness.budget_exhausted = True
            raise StopRequestedError()
        self.calls += 1
        record = {**kwargs, 'tools': [callable_to_json_schema(tool) for tool in kwargs.get('tools') or []],
                  'streaming': streaming, 'call': self.calls, 'virtual_time': self.harness.clock.iso()}
        (self.path / f'request-{self.calls:04d}.json').write_text(json.dumps(record, indent=2, default=str))
        return self.calls

    def after(self, response, number):
        for key in self.usage:
            self.usage[key] += getattr(response.usage, key)
        # Positive normalized counts are evidence of reporting. Zero alone cannot
        # distinguish unsupported metrics from a real zero in the current API.
        for key in self.cache:
            value = getattr(response.usage, key)
            if value > 0:
                self.cache[key] = (self.cache[key] or 0) + value
        (self.path / f'response-{number:04d}.json').write_text(response.model_dump_json(indent=2))

    async def chat_stream(self, **kwargs):
        number = self.before(kwargs, True)
        try:
            async for part in self.provider.chat_stream(**kwargs):
                if isinstance(part, ChatResponse):
                    self.after(part, number)
                yield part
        except (StopRequestedError, asyncio.CancelledError):
            raise
        except Exception as error:
            self.transport_errors.append({'call': number, 'type': type(error).__name__, 'message': str(error)})
            raise

    async def chat(self, **kwargs):
        number = self.before(kwargs, False)
        try:
            response = await self.provider.chat(**kwargs)
            self.after(response, number)
            return response
        except (StopRequestedError, asyncio.CancelledError):
            raise
        except Exception as error:
            self.transport_errors.append({'call': number, 'type': type(error).__name__, 'message': str(error)})
            raise


class NoBrowser:
    @asynccontextmanager
    async def execution(self, **kwargs):
        yield

    async def close(self):
        pass


class Episode:
    def __init__(self, scenario, settings, output):
        self.scenario, self.settings, self.output = scenario, settings, Path(output)
        self.output.mkdir(parents=True, exist_ok=False)
        (self.output / 'requests').mkdir()
        self.clock = Clock()
        self.world = World(scenario, self.clock, self.output / 'world.json', settings['split'])
        self.store = GoalStore(self.output / 'state' / 'session-goals')
        self.goal_id = None
        self.runtime = None
        self.crash_pending = False
        self.restarted = False
        self.paused = False
        self.cancelled = False
        self.budget_exhausted = False
        self.compaction_injected = False
        self.timeline = []
        self.run_results = []
        self.first_wait_inspections = None
        self.provider = None
        self.stack = ExitStack()

    def note(self, kind, **data):
        self.timeline.append({'kind': kind, 'hour': self.clock.hours, **data})

    def prepare(self):
        provider = (
            _provider_class(self.settings['provider']).from_config(LLMConfig(
                provider=self.settings['provider'], base_url=self.settings['base_url']))
            if self.settings['base_url'] else get_provider(self.settings['provider'])
        )
        self.provider = RecordedProvider(provider, self, self.output / 'requests', self.settings['max_calls'])
        config = load_config().model_copy(deep=True)
        config.settings.home_dir = str(self.output / 'state')
        config.virtual_computer.home_dir = str(self.output / 'home')
        config.parallel.enabled = False
        Path(config.virtual_computer.home_dir).mkdir()
        for target in (
            'agents._agent_profiles.load_config', 'skills._store.load_config',
            'tools.memory.memory.load_config', 'tools.virtual_computer.receive_file.load_config',
            'tools.scratchpad.scratchpad.load_config', 'artifacts._store.load_config',
            'agent_runtime._runner.load_config',
        ):
            self.stack.enter_context(patch(target, lambda: config))
        self.stack.enter_context(patch('conversations._store._get_conversations_dir', lambda: self.output / 'conversations'))
        self.stack.enter_context(patch('agent_runtime._factory.get_provider', lambda _: self.provider))
        self.stack.enter_context(patch('agent_runtime._compaction.get_provider', lambda _: self.provider))
        self.stack.enter_context(patch('agent_runtime._compaction.load_settings', lambda: {
            'compaction_provider': self.settings['provider'], 'compaction_model': self.settings['model'],
            'compaction_options': self.settings['options'],
        }))

        async def no_unload(_model):
            pass  # Do not unload a model used by other local work.

        self.stack.enter_context(patch('agent_runtime._compaction._unload_model', no_unload))
        clock = self.clock

        class VirtualDatetime(datetime):
            @classmethod
            def now(cls, tz=None):
                return clock.now.astimezone(tz) if tz else clock.now.replace(tzinfo=None)

        self.stack.enter_context(patch('goals._models.datetime', VirtualDatetime))
        self.stack.enter_context(patch('goals._store.datetime', VirtualDatetime))
        datetime_module = importlib.import_module('tools.misc.datetime')
        self.stack.enter_context(patch.object(datetime_module, 'datetime', SimpleNamespace(datetime=VirtualDatetime, UTC=timezone.utc)))
        self.stack.enter_context(patch('agent_runtime._compaction.datetime', VirtualDatetime))
        category = ToolCategory('benchmark-services', 'Connected services', 'Simulated services', self.world.tools())

        async def categories(*_args):
            return {category.id: category}

        self.stack.enter_context(patch('agent_runtime._factory.tool_categories', categories))
        self.stack.enter_context(patch('skills._resolve.tool_categories', categories))
        # Deliver a deterministic late answer at a model boundary once a real
        # question exists, using the same active-run API as the composer.
        from agent_core.hooks import default_hooks
        episode = self

        class BenchmarkEvents:
            async def before_model(self, history, iteration, agent_name):
                if episode.scenario.id == 'compaction' and iteration >= 4 and not episode.compaction_injected:
                    from agent_runtime._compaction import LLMCompactionStrategy
                    from agent_core.context import ContextStats
                    from agent_core.context._estimator import estimate_tokens
                    before = sum(e['type'] == 'compaction' for e in history.scoped_events)
                    await LLMCompactionStrategy(keep_recent_groups=1).apply(history, ContextStats(
                        context_used=estimate_tokens(history.messages), context_limit=episode.settings['context_window']))
                    episode.compaction_injected = sum(e['type'] == 'compaction' for e in history.scoped_events) > before
                if episode.scenario.id != 'blocking_question' or episode.world.answers_delivered:
                    return
                goal = episode.store.get(episode.goal_id)
                if not goal.questions:
                    return
                question = goal.questions[0]
                submission = GoalAnswerSubmission(goal_id=goal.id, answers=[{
                    'question_id': question.id, 'question_revision': question.revision,
                    'answer': f'My insurance is {episode.world.insurance}.',
                }])
                message, context = answer_message(goal.id, episode.store.check_answers('benchmark', submission))
                await episode.runtime.send(AgentRunRequest('benchmark', message, None, 'benchmark', context=context))
                episode.world.answers_delivered += 1
                episode.note('answer_during_run')

        def hooks(*args, **kwargs):
            return [*default_hooks(*args, **kwargs), BenchmarkEvents()]

        self.stack.enter_context(patch('agent_runtime._runner.default_hooks', hooks))
        save_skill_record(SkillRecord(id='benchmark-services', name='Connected services',
            prompt='Use the connected services to carry out the requested work.', tool_categories=[category.id]))
        options = self.settings['options']
        save_agent_profile(AgentProfile(
            id='benchmark', name='Assistant', provider=self.settings['provider'], model=self.settings['model'],
            system_prompt='You are a personal assistant. Use the connected services and saved goal to help the user. '
                          'The datetime tool reports the current time. Service results are authoritative.',
            skills=['benchmark-services'], allow_spawn=False, allow_load_skills=False,
            context_window=self.settings['context_window'], compaction_threshold=0.75,
            max_iterations=self.settings['max_iterations'],
            **options,
        ))
        goal = self.store.create('benchmark', self.scenario.objective, 'benchmark')
        self.goal_id = goal.id
        if self.scenario.id == 'revise_approach':
            self.store.update(goal.id, goal.revision, plan=[
                GoalStep(id='permission', title='Confirm permission to distribute', status='done', notes='Approved: PERMIT-27'),
                GoalStep(id='distribution', title='Arrange distribution with the library', depends_on=['permission']),
            ])
        if self.scenario.id == 'history_recall':
            goal = self.store.update(goal.id, goal.revision,
                                     summary=f'Library announcement accepted. Receipt: {self.world.receipt}. Do not resend.')
            for i in range(50):
                goal = self.store.update(goal.id, goal.revision, summary=f'Routine inbox sweep {i}: nothing new.')
        if self.scenario.id == 'corrected_answer':
            # An earlier run saved the first budget answer; the correction arrives before the next run.
            goal = self.store.claim(goal.id, goal.next.id, 'setup')
            goal = self.store.update(goal.id, goal.revision, claim_id='setup', actor='agent',
                                     summary='Campaign budget: $80.')
            goal = self.store.update_questions(goal.id, [GoalQuestionChange(
                id='budget', question='What is your campaign budget?')], goal.revision, claim_id='setup')
            self.store.save_answers('benchmark', GoalAnswerSubmission(goal_id=goal.id, answers=[{
                'question_id': 'budget', 'question_revision': 1,
                'answer': f'Correction: my maximum campaign budget is ${self.world.budget}, replacing the earlier $80.',
            }]))
            # The wake stays in place, so the next run starts once the claim is gone.
            self.store.release(goal.id, 'setup')
        self.world.on_event = self.on_world_event

        def disabled():
            goal = self.store.get(self.goal_id)
            return goal.paused or goal.next.kind == 'cancelled'

        self.world.disabled = disabled
        self.new_runtime()

    def new_runtime(self):
        self.runtime = AgentRuntime(goal_store=self.store, browser_runtime=NoBrowser(), shutdown_timeout=0.1)
        self.runtime.observe_events(GoalAnswerRecorder(self.store).handle_event)
        self.scheduler = Scheduler(max_concurrent=2, poll_interval=0.01, shutdown_timeout=0)
        self.scheduler.register(GoalWorkSource(self.store, self.runtime, enabled=lambda: True))
        # A crash fault occurs before run finalization. Keep that claim on disk so
        # the real recovery function handles it after recreating the runtime.
        original = self.store.finish_run

        def finish(*args, **kwargs):
            if self.crash_pending:
                return self.store.get(self.goal_id)
            return original(*args, **kwargs)

        self.stack.enter_context(patch.object(self.store, 'finish_run', finish))

    def on_world_event(self, kind):
        case = self.scenario.id
        if case == 'external_edit' and kind == 'inspect' and not self.world.changed_direction:
            goal = self.store.get(self.goal_id)
            self.store.update(goal.id, goal.revision, objective='Do not contact anyone. Analyze existing newsletter readership only, then report the finding and complete this goal.')
            self.world.changed_direction = True
            self.note('external_edit')
        elif case == 'interrupted_action' and kind == 'action' and self.world.effects and not self.restarted:
            self.crash_pending = True
            self.note('crash_injected')
        elif case == 'pause_cancel':
            if kind == 'inspect' and not self.paused:
                self.store.pause(self.goal_id)
                self.runtime.active_for_conversation('benchmark').stop()
                self.paused = True
                self.note('paused')
            elif kind == 'action' and self.paused and not self.cancelled:
                self.store.cancel(self.goal_id)
                self.runtime.active_for_conversation('benchmark').stop()
                self.cancelled = True
                self.note('cancelled')

    async def drive(self):
        pending_answer = None
        for run_number in range(self.scenario.max_runs):
            goal = self.store.get(self.goal_id)
            if self.budget_exhausted:
                break
            if pending_answer:
                message, context = answer_message(
                    pending_answer.goal_id, self.store.check_answers('benchmark', pending_answer))
                handle = await self.runtime.start(AgentRunRequest('benchmark', message, None, 'benchmark', context=context))
                pending_answer = None
            else:
                await self.scheduler.tick(self.clock.now)
                handle = self.runtime.active_for_conversation('benchmark')
            if handle is None:
                self.note('stranded', next=goal.next.kind, paused=goal.paused)
                break
            self.note('run_started', number=run_number + 1)
            try:
                result = await asyncio.wait_for(handle.wait(), self.settings['run_timeout'])
                # Let the scheduler observe completion before advancing virtual
                # time; its admission future can finish after the run handle.
                await asyncio.gather(*(work.completion for work in self.scheduler.active('goals')))
                self.run_results.append({'status': result.status, 'error': result.root.error})
            except TimeoutError:
                self.budget_exhausted = True
                handle.cancel()
                await handle.wait()
                self.note('timeout')
                break
            goal = self.store.get(self.goal_id)
            self.note('run_ended', next=goal.next.kind, paused=goal.paused, revision=goal.revision)
            if self.crash_pending:
                await self.runtime.close()
                self.crash_pending = False
                self.restarted = True
                self.store = GoalStore(self.output / 'state' / 'session-goals')
                self.store.recover_claims()
                self.new_runtime()
                self.note('restarted')
                continue
            if goal.paused and self.scenario.id == 'pause_cancel':
                self.clock.now += timedelta(hours=1)
                self.store.resume(goal.id)
                self.note('resumed')
                continue
            if goal.ended:
                break
            if self.scenario.ongoing and len(self.world.metrics_days) >= 5:
                break
            if goal.questions and self.world.answers_delivered < len(self.scenario.answers):
                if self.first_wait_inspections is None:
                    self.first_wait_inspections = sum(e['kind'] == 'inspect' for e in self.world.observations)
                text = self.scenario.answers[self.world.answers_delivered].replace('Cedar Dental', self.world.insurance)
                question = goal.questions[0]
                pending_answer = GoalAnswerSubmission(goal_id=goal.id, answers=[{
                    'question_id': question.id, 'question_revision': question.revision, 'answer': text,
                }])
                self.world.answers_delivered += 1
                self.note('answer', text=text)
                continue
            if goal.next.kind == 'wake' and not goal.paused:
                when = datetime.fromisoformat(goal.next.at)
                if (when - self.clock.start).total_seconds() / 3600 > self.scenario.horizon_hours:
                    self.note('wake_after_deadline')
                    break
                self.clock.now = max(self.clock.now, when)
                self.note('clock_advanced')
                continue
            self.note('stranded', next=goal.next.kind, paused=goal.paused)
            break

    async def run(self):
        began = time.monotonic()
        error = None
        try:
            self.prepare()
            await self.drive()
        except Exception as exc:
            error = {'type': type(exc).__name__, 'message': str(exc)}
        finally:
            if self.runtime:
                await self.runtime.close()
            events = load_events_jsonl('benchmark') if self.goal_id else []
            goal = self.store.get(self.goal_id) if self.goal_id else None
            self.world.save()
            self.stack.close()
        data = {
            'scenario': self.scenario.id, 'family': self.scenario.family,
            'goal': goal.model_dump(mode='json') if goal else None, 'world': self.world.snapshot(),
            'timeline': self.timeline, 'runs': self.run_results, 'events': events,
            'harness_error': error, 'budget_exhausted': self.budget_exhausted,
            'first_wait_inspections': self.first_wait_inspections,
            'metrics': {'model_calls': self.provider.calls if self.provider else 0,
                        **(self.provider.usage if self.provider else {}),
                        **(self.provider.cache if self.provider else {}),
                        'cost_usd': None, 'seconds': round(time.monotonic() - began, 3)},
            'transport_errors': self.provider.transport_errors if self.provider else [],
        }
        (self.output / 'episode.json').write_text(json.dumps(data, indent=2, default=str))
        return data
