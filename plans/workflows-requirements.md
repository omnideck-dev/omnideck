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
  (stop, or take a different path). A run can sit paused at an approval step
  indefinitely until the user acts — it is not a timeout.

### Data shaping
Most steps need the incoming data adjusted to fit. The user does this two ways:

- **Visual field mapping (no code, the default)** — point at available data and
  drop it into the fields a step needs. Covers the common cases.
- **Code (escape hatch)** — for shaping that's too complex to express by mapping,
  drop into a small piece of logic. The assistant can write it and the user can
  test it inline.

A *code step* and *code-based shaping* are the same idea — logic over the data.
The difference is only placement: a code step is its own box on the canvas; field
mapping and code shaping are attached to the step they feed.

### Structured results (from agent steps)
Because agent steps produce free-form output and tool/code steps need predictable
data, an agent step can be told to **return its answer in a defined shape** (e.g.
"give me back a list of items, each with a title and a due date"). Downstream
steps then get reliable, structured data instead of having to scrape it out of
prose.

### Connections (which account a step or trigger uses)
Many tools — and watch triggers — act through a **connected account**, and a
user may have several of the same type (two mailboxes, two calendars). The user
always controls which one is used, in one of two ways:

- **Pinned (the default)** — pick a specific account while building ("always send
  from my work Gmail").
- **Data-driven** — let the account be decided at runtime from the run's data, so
  a workflow can "reply from *whichever* mailbox received the message." This is
  filled by the same no-code field mapping as any other input.

The chosen account is **shown on the step itself**, so which account a step uses
is clear at a glance, not buried in a settings panel.

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
exact same tool-step machinery: pick a tool, pick the account, map in the
content.

The user configures, per workflow, **which events** should notify them — run
**failed** (on by default), run **finished**, or a run **needs approval** — and
**which tool** delivers each. An approval notification carries a link back to the
app, where the user actually approves or rejects.

### What data a step can see
At any step, the user has access to **everything produced so far** in the run:
the data the workflow started with, plus the output of every earlier step,
each labeled by name. So a step late in the workflow can still reach back to,
say, the original email that kicked things off — it doesn't get lost along the
way.

### Trigger
A **Trigger** is what starts a workflow. Triggers are separate from the workflow
itself, so one workflow can be started in more than one way, and can always be
run manually too. There are two kinds:

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
6. **Choose which connected account** a step or trigger uses — pinned to a
   specific account, or decided at runtime from the run's data.
7. **Shape data without code** via visual field mapping, dropping into code only
   when needed.
8. **Branch** — send the workflow down different paths based on the data.
9. **Loop** — repeat a section of the workflow once per item in a list.
10. **Pause for human approval** — stop a run at a checkpoint, get notified, and
    approve or reject before it continues (e.g. before sending an email).
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
18. **Start workflows three ways** — on a schedule, when something is detected,
    or manually.
19. **Watch the world and react** — set up a watch trigger that polls a tool and
    fires only on genuinely new, matching items, within a safe volume limit, and
    can watch several accounts of the same type at once.
20. **Inspect any run** — see which path it took, what each step received and
    produced, and exactly where it succeeded or failed, including runs paused
    waiting for approval.

## 5. How triggers behave (from the user's side)

### Schedule trigger
The user picks a schedule and a workflow. The workflow runs on that schedule.
Simple.

### Watch trigger
The user picks a tool to watch (e.g. "list inbox messages"), how often to check,
and a **condition** that decides whether an item is worth acting on. The
assistant can help write the condition. A single watch trigger can watch
**several accounts of the same type at once** (e.g. both mailboxes); each item it
finds carries which account it came from, so downstream steps can act on the
right one.

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
- Tool step: which tool, which connected account to use (pinned or data-driven),
  and how its inputs are filled from the available data (by visual mapping).
- Code step: the logic to run.
- Branch step: the rule that decides the path.
- Loop step: which list to iterate over, and what to do per item.
- Approval step: what to show the user when it pauses, and what approve vs reject
  each do (continue, stop, or route down a different path).
- Any step: optional data shaping on the way in or out, how many times to retry on
  failure, and what to do if it ultimately fails (stop / error path / skip).

### Picking a connected account
- Where a step or trigger acts through an account, an **account picker** lists the
  user's connected accounts that can do that action, labeled clearly (type +
  which account).
- The picker is **permission-aware**: accounts that lack the needed access are
  shown **disabled with a short reason** ("read-only — can't send"), so the user
  understands why and can go fix it, rather than silently not seeing it.
- The selected account appears **on the face of the step**. If a chosen account
  later breaks or loses permission, the step shows a clear warning.

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
- **Single step:** run one step (or just its data shaping) against sample data.
- **Whole workflow:** dry-run the entire workflow end to end.
- **Sample data** comes from either a **previous real run** (replayed) or **data
  the user pastes in**.
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
  under review and approve/reject controls right there.

## 7. Example scenarios

- **Morning briefing (schedule):** Every weekday at 7am → an agent step gathers
  news → an agent step (different profile) writes a summary → a tool step emails
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
  on approve, a tool step sends it; on reject, the run stops (or loops back for a
  revised draft).

## 8. Relationship to today's Goals

- Workflows are built **alongside** Goals, not as an in-place replacement. Goals
  keep working until Workflows reach parity, then Goals are retired.
- A migration path (converting existing Goals into equivalent Workflows) is
  desirable but is a later concern, not a v1 requirement.

## 9. Out of scope (for now)

- Sharing/marketplace of workflows between users.
- Versioning and rollback of a workflow's definition.
- Collaborative / multi-user editing of the same workflow.

## 10. Open questions (user-facing)

These need a user-facing answer before or during design:

1. **Naming.** Are *Workflow*, *Trigger*, *Step* the right user-facing words?
   "Trigger" is still a working title.
2. **Approval step details.** Does a paused run ever expire, or wait forever
   (current assumption: waits forever)? On reject, is "stop" or "take another
   path" the default?
3. **Editing a live workflow.** If a workflow is scheduled or mid-run when the
   user edits it, what should happen — to in-flight runs and to the next run?

### Resolved
- **Step failure** — per-step retries, then stop / error path / skip; loops are
  best-effort by default; run history shows retries and the path taken.
- **Notifications** — no dedicated system; the user is notified by calling any
  integration tool they've connected, configured per workflow per event
  (failure on by default). Telegram-specific notification is dropped for now.
- **Connections** — pinned or data-driven account selection, a permission-aware
  picker that shows unusable accounts disabled with a reason, and the chosen
  account shown on the step. Watch triggers can watch multiple accounts at once.
