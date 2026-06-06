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
  gathered back together when the loop finishes.
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
6. **Shape data without code** via visual field mapping, dropping into code only
   when needed.
7. **Branch** — send the workflow down different paths based on the data.
8. **Loop** — repeat a section of the workflow once per item in a list.
9. **Pause for human approval** — stop a run at a checkpoint, get notified, and
   approve or reject before it continues (e.g. before sending an email).
10. **Reach back** to any earlier step's output (and the starting data) from any
   later step.
11. **Get AI help while building** — ask the assistant to build a step, write
    logic, wire a tool step's inputs, or explain an existing step.
12. **Test a single step** against sample data and see the result.
13. **Dry-run the whole workflow** end to end before going live, with real-world
    actions held back by default.
14. **Use real or made-up test data** — test against data captured from a
    previous real run, or against sample data they paste in.
15. **Start workflows three ways** — on a schedule, when something is detected,
    or manually.
16. **Watch the world and react** — set up a watch trigger that polls a tool and
    fires only on genuinely new, matching items, within a safe volume limit.
17. **Inspect any run** — see which path it took, what each step received and
    produced, and exactly where it succeeded or failed, including runs paused
    waiting for approval.

## 5. How triggers behave (from the user's side)

### Schedule trigger
The user picks a schedule and a workflow. The workflow runs on that schedule.
Simple.

### Watch trigger
The user picks a tool to watch (e.g. "list inbox messages"), how often to check,
and a **condition** that decides whether an item is worth acting on. The
assistant can help write the condition.

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
- Tool step: which tool, which connected account/integration to use, and how its
  inputs are filled from the available data (by visual mapping).
- Code step: the logic to run.
- Branch step: the rule that decides the path.
- Loop step: which list to iterate over, and what to do per item.
- Approval step: what to show the user when it pauses, and what approve vs reject
  each do (continue, stop, or route down a different path).
- Any step: optional data shaping on the way in or out.

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
- When a run fails, the user can see exactly which step failed and why.
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
2. **When a step fails mid-run**, what should the user experience? Retry the
   step automatically? Stop the run? Take an "on error" path? What does the run
   history show?
3. **Notifications.** When and how should a user be told a run finished, failed,
   or needs attention? (Today's system notifies via Telegram on completion /
   failure.)
4. **Connections in tool steps.** When a user has several connected accounts of
   the same type (e.g. two mailboxes), how do they pick which one a tool step
   uses, and how clear is that in the editor?
5. **Approval step details.** Where does the user get notified and act —
   in-app only, or also via the notification channel (e.g. Telegram)? Can they
   approve from there? Does a paused run ever expire, or wait forever? On reject,
   is "stop" or "take another path" the default?
6. **Editing a live workflow.** If a workflow is scheduled or mid-run when the
   user edits it, what should happen — to in-flight runs and to the next run?
