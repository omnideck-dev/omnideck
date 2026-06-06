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
multi-step automation**, and an AI assistant is available the whole time to help
them build it.

## 2. Who builds them, and how it should feel

The user builds workflows in a **visual editor** (WYSIWYG): a canvas of step
boxes connected by lines showing how data flows. They drag in steps, connect
them, configure each one, and watch data move through.

Three things define the experience:

- **Visual and direct.** You see the whole workflow as a diagram. You connect
  steps by drawing a line. You see, at any point, what data is available.
- **AI-assisted while you build.** The default assistant is available *inside*
  the editor. You can ask it to "write a step that pulls the sender and subject
  out of this email," or "turn this into a JSON the next step expects," and it
  builds that step or that bit of data-shaping for you.
- **Testable before it's live.** You never have to guess whether a step works.
  You can run a single step (or just its data-shaping) against real sample data
  and see exactly what comes out — before the workflow ever runs for real.

## 3. Core concepts (in user terms)

### Workflow
The whole automation: a named diagram of steps and the connections between them.

### Step
A single box on the canvas. Every step takes some data in and produces some data
out. There are a few kinds:

- **Agent step** — an AI agent does the work, following an instruction you write.
  Each agent step can use a **different agent profile** (e.g. a research agent for
  one step, a writing agent for the next).
- **Tool step** — runs a tool directly and reliably, with no AI in the loop
  (e.g. "send this email," "create this calendar event," "call this API").
  This is how a workflow takes a concrete action.
- **Code step** — runs a small piece of logic to compute or reshape data
  (e.g. "filter this list down to items from this week").
- **Branch step** — looks at the data and decides which path the workflow takes
  next (e.g. "if the email is from my boss, go this way; otherwise, that way").

### Data shaping (formatters)
Any step can have an **input formatter** and/or an **output formatter** — a small
transformation applied to the data as it enters or leaves the step. This is how
you adapt the output of one step to fit what the next step needs, without
rewriting the steps themselves. Formatters are optional; many steps won't need
them.

The user does not have to write these by hand — the in-editor assistant can
generate them, and the user can test them inline.

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
4. **Take real actions** at the end of (or anywhere in) a workflow via tool
   steps — send an email, file a document, post to an API.
5. **Reshape data between steps** with input/output formatters.
6. **Branch** — send the workflow down different paths based on the data.
7. **Reach back** to any earlier step's output (and the starting data) from any
   later step.
8. **Get AI help while building** — ask the assistant to write a formatter, a
   code step, an agent instruction, or to wire a tool step's inputs.
9. **Test inline** — run a single step or formatter against sample data and see
   the result, without running the whole workflow.
10. **Use real or made-up test data** — test against data captured from a
    previous real run, or against sample data they paste in.
11. **Start workflows three ways** — on a schedule, when something is detected,
    or manually.
12. **Watch the world and react** — set up a watch trigger that polls a tool and
    fires only on genuinely new, matching items.
13. **See run history** — review past runs, what each step produced, and what
    succeeded or failed.

## 5. How triggers behave (from the user's side)

### Schedule trigger
The user picks a schedule and a workflow. The workflow runs on that schedule.
Simple.

### Watch trigger
The user picks a tool to watch (e.g. "list inbox messages"), how often to check,
and a **condition** that decides whether an item is worth acting on. The
assistant can help write the condition.

Two behaviors the user should be able to count on:

- **No duplicate reactions.** If the watch finds something it already acted on,
  it won't fire again for the same thing. "New email from a client" means *new* —
  the user won't get re-triggered on the same email every few minutes.
- **One run per item, by default.** If three new matching emails show up at once,
  the user gets three runs — one per email — each with that email's data. (A user
  who wants the opposite — one run handling the whole batch — can choose that
  instead.)

## 6. Building experience — the editor in detail

### The canvas
- Steps appear as boxes; connections appear as lines showing the flow of data.
- The user adds steps, connects them, and rearranges freely.
- Branch steps visibly split the flow into multiple paths; paths can rejoin.

### Configuring a step
Each step's box exposes what that kind of step needs:
- Agent step: an instruction and a choice of agent profile.
- Tool step: which tool, which connected account/integration to use, and how its
  inputs are filled from the available data.
- Code step: the logic to run.
- Branch step: the rule that decides the path.
- Any step: optional input/output formatters.

### The in-editor assistant
- Available on any step. The user describes what they want in plain language.
- The assistant can see **what data is available at that point in the
  workflow**, so it can write formatters, code, instructions, and tool-input
  mappings that actually fit the real data.
- Whatever the assistant produces, the user can immediately **test** before
  keeping it.

### Inline testing
- Run a single step, or just a formatter, against sample data.
- Sample data comes from either a **previous real run** (replayed) or **data the
  user pastes in**.
- The user sees the exact output, so building is build → test → adjust, not
  build → deploy → hope.

## 7. Example scenarios

- **Morning briefing (schedule):** Every weekday at 7am → an agent step gathers
  news → an agent step (different profile) writes a summary → a tool step emails
  it to the user.
- **Client email triage (watch):** Check inbox every 5 min → when a new email
  from a known client arrives → a branch step routes "urgent" vs "normal" → the
  urgent path drafts a reply and notifies the user; the normal path files it and
  logs it.
- **Form-to-spreadsheet (watch + deterministic):** Watch an API for new form
  submissions → a code step reshapes the submission → a tool step appends it to a
  sheet. No AI involved at all — but built in the same editor.
- **Mixed (everything):** Watch for new invoices → an agent step extracts line
  items → a code step validates the totals → a branch step flags mismatches for a
  human while clean ones flow to a tool step that records them.

## 8. Relationship to today's Goals

- Workflows are built **alongside** Goals, not as an in-place replacement. Goals
  keep working until Workflows reach parity, then Goals are retired.
- A migration path (converting existing Goals into equivalent Workflows) is
  desirable but is a later concern, not a v1 requirement.

## 9. Out of scope (for now)

- Sharing/marketplace of workflows between users.
- Versioning and rollback of a workflow's definition.
- Collaborative / multi-user editing of the same workflow.
- Human-in-the-loop *approval* steps that pause a run awaiting a user's click.
  (Worth revisiting — branch + notify covers part of this, but not a true pause.)

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
5. **Human approval steps.** Is a true "pause and wait for me to approve" step a
   v1 need, or a later addition?
