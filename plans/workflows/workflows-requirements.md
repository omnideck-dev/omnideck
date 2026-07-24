# Workflows — Requirements (User Perspective)

> **Status:** Draft for discussion. *Workflows* and *Triggers* are working titles.
> This document describes what a user can do and how it should feel to use.
> It is intentionally free of implementation detail — the technical design
> follows separately.

## 1. What Workflows are (and what they replace)

A **Workflow** is something a user builds to get a job done automatically: a
series of connected **steps** that pass data from one to the next. Some steps
think (they use an AI agent); some steps just *do* (they run a tool or a bit of
logic deterministically). A workflow can run on a schedule, run when something
happens out in the world, or be run by hand.

Workflows replace today's **Goals**. Where a Goal was a description handed to an
agent, a Workflow is something the user *assembles* visually and can reason
about, test, and trust — including the parts that don't involve AI at all.

The guiding principle: **a non-programmer should be able to build a real,
multi-step automation.** Two things make that possible: the common data-shaping
tasks are done with **no-code visual mapping**, not code; and an AI assistant is
available the whole time to handle the harder parts and to explain what it built.

## 2. Who builds them, and how it should feel

The user builds workflows in a **visual editor** (WYSIWYG): a canvas of step
boxes connected by lines showing how data flows. They drag in steps, connect
them, configure each one, and watch data move through.

Four things define the experience:

- **Visual and direct.** You see the whole workflow as a diagram. You connect
  steps by drawing a line. You see, at any point, what data is available.
- **No-code by default.** Routine data shaping — "put the sender's address into
  the reply's *To* field" — is done by pointing at fields, not writing code.
  Code is available as an escape hatch, not the price of entry.
- **AI-assisted while you build.** The default assistant is available *inside*
  the editor. You can ask it to build a step, write a tricky bit of logic, or
  explain what an existing step does.
- **Testable before it's live.** You never have to guess. You can test a single
  step, or dry-run the whole workflow, against real or sample data — and during a
  test, real-world actions (sending email, etc.) are held back unless you say
  otherwise.

## 3. Core concepts (in user terms)

### Workflow
The whole automation: a named diagram of steps and the connections between them.

### Step
A single box on the canvas. Every step takes some data in and produces some data
out. There are a few kinds:

- **Agent step** — an AI agent does the work, following an instruction you write.
  Each agent step can use a **different agent profile** (e.g. a research agent for
  one step, a writing agent for the next). An agent step can also be told to
  **return its result in a specific shape** (see "Structured results" below) so
  the next step can rely on it.
- **Tool step** — runs a tool directly and reliably, with no AI in the loop
  (e.g. "send this email," "create this calendar event," "call this API").
  This is how a workflow takes a concrete action.
- **Code step** — runs a piece of logic that's too involved for visual mapping
  (e.g. "score each item and keep the top three"). The assistant can write it;
  the user can test it.
- **Branch step** — looks at the data and decides which path the workflow takes
  next (e.g. "if the email is from my boss, go this way; otherwise, that way").
- **Loop step** — runs a section of the workflow **once for each item** in a list
  (e.g. "for each action item the agent found, create a task"). Results are
  gathered back together when the loop finishes. By default a loop is
  **best-effort**: if one item fails, the rest keep going and the failures are
  reported at the end (the user can switch this to "stop the whole loop").
- **Approval step (human-in-the-loop)** — **pauses the run** and waits for the
  user to weigh in before continuing (e.g. "draft this reply, then wait for me to
  approve it before sending"). The user is notified that something needs their
  attention, sees the relevant data, and can **approve** (continue) or **reject**
  (stops the run for now). A run can sit paused at an approval step
  indefinitely until the user acts — it is not a timeout. The user can respond
  **two ways, interchangeably**: in the app, or **from outside it** — through the
  same kind of integration tool used for notifications, so an approval can be
  granted by replying to the message that announced it (e.g. reply "approve" to
  the email, or tap a button in a chat message). Whichever channel responds
  first resolves the pause; the request clears from the others. See "Approvals"
  under Notifications for how this is configured.

### Data shaping
Most steps need the incoming data adjusted to fit. There is one no-code way to do
this inline:

- **Visual field mapping (no code, the default)** — point at available data and
  drop it into the fields a step needs. Covers the common cases.

When shaping is too complex to express by mapping, the user adds a **code step**
before the step that needs the data — there is no separate "code attached to a
step." Code lives in exactly one place, its own box on the canvas, where it can be
seen, tested, and reused. (The assistant can write the code step; the user can
test it.)

> **Note (asymmetry of mapping).** Visual field mapping points *into* typed
> fields, so a step's **inputs** map cleanly — tool inputs in particular have a
> defined schema. But many step **outputs are free text by design** (tool results,
> and agent results that weren't given a defined shape), so there are no fields to
> point *at* on the source side. Mapping from a text output can only take it as a
> whole value; to get structure out of it, either request a **structured result**
> from an agent step (see below) or add a **code step** to parse it.

### Structured results (from agent steps)
Because agent steps produce free-form output and tool/code steps need predictable
data, an agent step can be told to **return its answer in a defined shape** (e.g.
"give me back a list of items, each with a title and a due date"). Downstream
steps then get reliable, structured data instead of having to scrape it out of
prose.

The user just describes the shape they want — with help from the in-line
assistant — and nothing more. How that shape is enforced is entirely the engine's
problem and is never exposed to the user. If the chosen agent's model can't
reliably produce the shape, that shows up as a clear failure during a **dry run**,
where the user can switch to a more capable model — they are never asked to reason
about model capabilities up front.

### Integrations (which integration a step or trigger uses)
Many tools — and watch triggers — act through an **integration**, and a
user may have several of the same type (two mailboxes, two calendars). The user
**pins** a specific integration while building ("always send from my work Gmail").
For v1 the integration is always chosen explicitly; deciding it at runtime from the
run's data (e.g. "reply from *whichever* mailbox received the message") is out of
scope (see §9).

The chosen integration is **shown on the step itself**, so which integration a step
uses is clear at a glance, not buried in a settings panel.

### Handling failure
A step can stumble (a flaky API, a timeout). The user controls what happens:

- **Retry** — each step can retry a configurable number of times first, so
  transient blips never bother the user.
- **Then one of:** *stop the run* (the safe default), *take an error path* (a
  separate connection drawn from the step, so the workflow can clean up, send a
  fallback, or notify), or *skip and continue* (for best-effort steps).

### Notifications
There is **no separate notification system** — a notification is simply **one of
the user's own tools being called** (send an email, post a message, etc.) through
an integration they've connected. Telling a user something happened reuses the
exact same tool-step machinery: pick a tool, pick the integration, map in the
content.

The user configures, per workflow, **which events** should notify them — run
**failed** (on by default), run **finished**, or a run **needs approval** — and
**which tool** delivers each.

**Approvals (notify and respond out-of-app).** A *needs approval* notification is
not just an alert with a link — it is a two-way exchange the user can complete
without ever opening the app:

- It is **delivered** by an integration tool, like any other notification (send
  an email, post a chat message), carrying the data under review.
- It can also be **answered** through an integration tool, so the user approves or
  rejects **in the same place they were notified** — reply "approve"/"reject" to
  the email, tap a button in the chat message. The user picks, per approval step,
  the tool that delivers the request and how the response comes back (the
  assistant can help wire this).
- The **app is always a valid response channel too.** Every paused approval shows
  in the app with the data under review and approve/reject controls, even when an
  out-of-app channel is also configured. The two are interchangeable: whichever
  responds first wins, and the request is then withdrawn from the other channels.

### What data a step can see
At any step, the user has access to **everything produced so far** in the run:
the data the workflow started with, plus the output of every earlier step,
each labeled by name. So a step late in the workflow can still reach back to,
say, the original email that kicked things off — it doesn't get lost along the
way.

### Trigger
A **Trigger** is what starts a workflow **on its own, without the user** — on a
schedule, or in response to something happening in the world. A trigger **belongs
to the workflow it starts** (defined and managed within that workflow, not a shared
object attached to others), and a workflow can have **more than one**.

**Manual run is not a trigger.** Every workflow can always be **run by hand**
("Run now") — that's just the user starting it themselves, available regardless of
what triggers (if any) are configured. Triggers are reserved for starts that
happen *without* the user. A workflow can have no triggers at all and simply be
run manually.

There are two kinds of trigger:

- **Schedule (cron) trigger** — run the workflow on a recurring schedule
  ("every weekday at 9am").
- **Watch (tool-poll) trigger** — keep an eye on something via a tool, and start
  the workflow when a condition is met, feeding in the relevant data. For
  example: *check my inbox every 5 minutes; when a new email arrives from a
  client, start the "draft a reply" workflow with that email's contents.*

## 4. What a user can do — capabilities

1. **Build a workflow visually** by adding steps and connecting them.
2. **Mix thinking and doing** — combine AI agent steps with deterministic tool
   and code steps in one workflow.
3. **Use a different agent profile per agent step.**
4. **Get structured results from agent steps** so later steps can rely on them.
5. **Take real actions** at the end of (or anywhere in) a workflow via tool
   steps — send an email, file a document, post to an API.
6. **Choose which integration** a step or trigger uses — pinned to a
   specific integration.
7. **Shape data without code** via visual field mapping, adding a code step
   before the consumer when mapping isn't enough.
8. **Branch** — send the workflow down different paths based on the data.
9. **Loop** — repeat a section of the workflow once per item in a list.
10. **Pause for human approval** — stop a run at a checkpoint, get notified, and
    approve or reject before it continues (e.g. before sending an email) — either
    in the app or out-of-app by responding through an integration tool.
11. **Handle failures gracefully** — retry a step, then stop the run, take an
    error path, or skip and continue, as configured.
12. **Reach back** to any earlier step's output (and the starting data) from any
    later step.
13. **Get AI help while building** — ask the assistant to build a step, write
    logic, wire a tool step's inputs, or explain an existing step.
14. **Test a single step** against sample data and see the result.
15. **Dry-run the whole workflow** end to end before going live, with real-world
    actions held back by default.
16. **Use real or made-up test data** — test against data captured from a
    previous real run, or against sample data they paste in.
17. **Be notified their own way** — get told about failures, completions, or
    approvals through any integration tool they've connected.
18. **Start a workflow by trigger or by hand** — automatically via a trigger (on a
    schedule or when something is detected), or run it manually any time.
19. **Watch the world and react** — set up a watch trigger that polls a tool and
    fires only on genuinely new, matching items, within a safe volume limit, and
    can watch several integrations of the same type at once.
20. **Inspect any run** — see which path it took, what each step received and
    produced, and exactly where it succeeded or failed, including runs paused
    waiting for approval.

## 5. How triggers behave (from the user's side)

### Schedule trigger
The user picks a schedule and a workflow. The workflow runs on that schedule.
Simple.

### Watch trigger
The user picks something to watch — a list/poll tool on an integration (a mailbox
folder, a Drive folder, a calendar, a contacts list, an API endpoint) — how often
to check, and a **condition** that decides whether an item is worth acting on.

The condition is a **no-code rule over the watched item's fields** — the same
field → operator → value builder used by a Branch step, except the available
fields are **supplied by the chosen tool** (an email has *from / subject / folder*;
a Drive file has *name / type / modified*; a calendar event has *summary / start*;
an API has no fixed shape, so it falls back to an expression over the response).
The assistant can write the rule from a plain-language description. The rule is
evaluated **deterministically per item on each poll** — it is not an LLM call;
fuzzy judgement belongs in an agent step inside the workflow, not the trigger
filter. (See the watchable-tools list and per-tool fields in the design.)

A single watch trigger can watch **several integrations of the same type at once**
(e.g. both mailboxes); each item it finds carries which integration it came from,
so downstream steps can act on the right one.

Three behaviors the user should be able to count on:

- **No duplicate reactions.** If the watch finds something it already acted on,
  it won't fire again for the same thing. "New email from a client" means *new* —
  the user won't get re-triggered on the same email every few minutes.
- **One run per item, by default.** If three new matching emails show up at once,
  the user gets three runs — one per email — each with that email's data. (A user
  who wants the opposite — one run handling the whole batch — can choose that
  instead.)
- **A safety limit on volume.** If a single check turns up an unexpectedly large
  number of new items, the workflow won't fan out into hundreds of runs blindly.
  There's a cap, and the user decides what happens to the overflow (hold for the
  next check, or skip).

## 6. Building experience — the editor in detail

### The canvas
- Steps appear as boxes; connections appear as lines showing the flow of data.
- The user adds steps, connects them, and rearranges freely.
- Branch steps visibly split the flow into multiple paths; paths can rejoin.
- Loop steps visibly enclose the section that repeats.

### Configuring a step
Each step's box exposes what that kind of step needs:
- Agent step: an instruction, a choice of agent profile, and (optionally) the
  shape of result to return.
- Tool step: which tool, which integration to use (pinned),
  and how its inputs are filled from the available data (by visual mapping).
- Code step: the logic to run.
- Branch step: the rule that decides the path.
- Loop step: which list to iterate over, and what to do per item.
- Approval step: what to show the user when it pauses, what approve vs reject
  each do (approve continues; reject stops the run for now), and **how the user is
  asked and responds** — which integration tool delivers the request and which
  brings the answer back, with the in-app approval always available alongside.
- Any step: optional visual field mapping to fill its inputs from available data,
  how many times to retry on failure, and what to do if it ultimately fails
  (stop / error path / skip). Anything beyond mapping is a code step placed before
  it.

### Picking an integration
- Where a step or trigger acts through an integration, an **integration picker**
  lists the user's connected integrations that can do that action, labeled clearly
  (type + which integration).
- The picker is **permission-aware**: integrations that lack the needed access are
  shown **disabled with a short reason** ("read-only — can't send"), so the user
  understands why and can go fix it, rather than silently not seeing it.
- The selected integration appears **on the face of the step**. If a chosen
  integration later breaks or loses permission, the step shows a clear warning.

### The in-editor assistant
- Available on any step. The user describes what they want in plain language.
- The assistant can see **what data is available at that point in the
  workflow**, so it can build steps, logic, and input mappings that actually fit
  the real data.
- It can also **explain** an existing step in plain language — important when the
  user can't read the underlying logic themselves.
- Whatever the assistant produces, the user can immediately **test** before
  keeping it.

### Testing
- **Single step:** run one step (a code step included) against sample data.
- **Whole workflow:** dry-run the entire workflow end to end.
- **Sample data** comes from either a **previous real run** (replayed) or **data
  the user pastes in** or **data generated by the in-editor assistant**.
- **Side effects are held back during tests.** A test won't actually send the
  email or write the file unless the user explicitly opts in; otherwise those
  actions are simulated so the user can see what *would* happen safely.
- The user sees the exact output at each step, so building is build → test →
  adjust, not build → deploy → hope.

### Inspecting runs
- Every real run is recorded: the path taken, each step's input and output, and
  any errors.
- For branching/looping workflows, the user can see **which branch fired** and
  **what happened on each loop iteration**.
- When a step fails, the user can see exactly which step failed and why, **how
  many times it was retried**, and — if an error path was taken — that the run
  continued down it.
- A run **paused at an approval step** is clearly shown as waiting, with the data
  under review and approve/reject controls right there. If the user instead
  responds out-of-app (e.g. by replying to the notification), the run reflects the
  decision and which channel it came through.

## 7. Example scenarios

- **Morning briefing (schedule):** Every weekday at 7am → an agent step gathers
  news → an agent step (different profile) writes a summary → -> an agent step 
  (different profile) converts the summary to audio -> a tool step emails
  it to the user.
- **Client email triage (watch + branch):** Check inbox every 5 min → when a new
  email from a known client arrives → a branch step routes "urgent" vs "normal" →
  the urgent path drafts a reply and notifies the user; the normal path files it
  and logs it.
- **Action items (agent → loop → tool):** An agent step reads a meeting note and
  returns a structured list of action items → a loop step creates a task for each
  one via a tool step.
- **Form-to-spreadsheet (watch + deterministic):** Watch an API for new form
  submissions → a code step reshapes the submission → a tool step appends it to a
  sheet. No AI involved at all — but built in the same editor.
- **Mixed (everything):** Watch for new invoices → an agent step extracts line
  items as structured data → a code step validates the totals → a branch step
  flags mismatches for a human while clean ones flow to a tool step that records
  them.
- **Reply with approval (human-in-the-loop):** A new client email arrives → an
  agent step drafts a reply → an **approval step** pauses and shows the draft →
  on approve, a tool step sends it; on reject, the run stops.
- **Process receipts:** Watch a drive folder for new files -> an agent step processes
  the image extracting key values from a receipt -> a tool step appends the values
  to a spreadsheet -> a tool step archives the processed receipt.

## 8. Relationship to today's Goals

- Workflows are built **alongside** Goals, not as an in-place replacement. Goals
  keep working until Workflows reach parity, then Goals are retired.
- A migration path (converting existing Goals into equivalent Workflows) is
  desirable but is a later concern, not a v1 requirement.

## 9. Out of scope (for now)

- Sharing/marketplace of workflows between users.
- Versioning and rollback of a workflow's definition.
- Collaborative / multi-user editing of the same workflow.
- Data-driven integration selection (deciding which integration a step or
  trigger uses at runtime from the run's data). v1 pins integrations explicitly.

## 10. Open questions (user-facing)

All current open questions are resolved (below). New ones may surface during
design.

### Resolved
- **Step failure** — per-step retries, then stop / error path / skip; loops are
  best-effort by default; run history shows retries and the path taken.
- **Notifications** — no dedicated system; the user is notified by calling any
  integration tool they've connected, configured per workflow per event
  (failure on by default). Telegram-specific notification is dropped for now.
- **Integrations** — pinned (explicit) integration selection, a permission-aware
  picker that shows unusable integrations disabled with a reason, and the chosen
  integration shown on the step. Watch triggers can watch multiple integrations at
  once.
- **Approval response channels** — an approval can be both delivered and answered
  through an integration tool, so the user can approve/reject without opening the
  app; the in-app approval is always available too, and the channels are
  interchangeable (first response wins, the rest are withdrawn).
- **Reject behavior** — on reject, the run **stops** for now (taking a different
  path is deferred).
- **Naming** — *Workflow*, *Step*, *Trigger* are the user-facing terms.
- **Approval expiry** — a paused approval **never expires**; the run waits until
  the user responds.
- **Editing a live workflow** — **in-flight runs finish on the definition they
  started with**; **the next run picks up the edits.** (Each run captures the
  workflow as it was at launch — this is internal pinning, not the user-facing
  version history that §9 defers.)
