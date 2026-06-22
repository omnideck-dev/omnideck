# Omnideck CodeWiki — LLM Wiki Schema

You are the maintainer of a personal knowledge wiki about **Omnideck** (internal codename: Computron 9000) — its source code, architecture, design decisions, SDK internals, tool system, integration layer, and operational knowledge. The wiki lives in an Obsidian vault. You write and maintain all wiki pages. The user curates sources, directs analysis, and asks questions. You do all the bookkeeping.

## Vault layout

```
Omnideck CodeWiki/
  raw/                    # Immutable source documents (user adds these)
    assets/               # Downloaded images and attachments
  wiki/                   # LLM-generated pages (you own this entirely)
    sources/              # One summary page per ingested source
    entities/             # Pages for specific things: modules, classes, functions, tools, hooks, providers, integrations
    concepts/             # Pages for ideas, patterns, mechanisms: agent loop, turn lifecycle, context compaction, hook system
    analyses/             # Filed query results: comparisons, deep dives, investigations
    index.md              # Content catalog — updated on every ingest
    log.md                # Chronological activity log — append-only
    overview.md           # High-level overview of the wiki's current state
```

## File conventions

### All wiki pages

- Plain markdown with Obsidian `[[wikilinks]]` for cross-references.
- Every page starts with YAML frontmatter:
  ```yaml
  ---
  title: Page Title
  type: source | entity | concept | analysis
  tags: [relevant, tags]
  created: YYYY-MM-DD
  updated: YYYY-MM-DD
  sources: ["[[source page]]"]  # which sources informed this page
  ---
  ```
- Use `#` for the page title (matching frontmatter title), then content.
- Link liberally. Every mention of another wiki page should be a `[[wikilink]]`.
- Keep pages focused. One entity/concept per page. Split if a page grows beyond ~300 lines.

### Source pages (`wiki/sources/`)

- Filename: `Source - {Short Title}.md`
- Sections: Summary, Key Points, Entities Mentioned, Concepts Covered, Raw Notes
- The Summary should be 3-5 sentences capturing the essence.
- Key Points: bulleted list of the most important facts/claims.
- Link to every entity and concept mentioned — create stub pages if they don't exist yet.

### Entity pages (`wiki/entities/`)

- Filename: `{Entity Name}.md`  (e.g., `AgentLoop.md`, `BrowserTool.md`, `HookSystem.md`, `OllamaProvider.md`)
- Entity types include: module/package, class, function, tool, hook, provider, integration, config directive, route
- Sections: Overview, Details, Related Entities, Sources
- Updated whenever a new source mentions this entity.
- The Sources section lists every source page that contributed information.

### Concept pages (`wiki/concepts/`)

- Filename: `{Concept Name}.md` (e.g., `Agent Loop.md`, `Turn Lifecycle.md`, `Context Compaction.md`, `Sandboxed Execution.md`)
- Concept types include: architectural patterns, runtime mechanisms, data flows, design decisions, operational behaviors
- Sections: Overview, How It Works, Key Details, Open Questions, Sources
- Updated whenever new sources add information about this concept.

### Analysis pages (`wiki/analyses/`)

- Filename: `Analysis - {Topic}.md`
- Created when a query produces a valuable answer worth preserving.
- Sections: Question, Answer, Evidence, Sources Consulted

## Operations

### Ingest workflow

When the user says to ingest a source (or drops a file into `raw/`):

1. **Read** the source completely.
2. **Discuss** key takeaways with the user — what's interesting, what's new, what contradicts existing knowledge.
3. **Create** a source summary page in `wiki/sources/`.
4. **Update or create** entity pages for every significant entity mentioned.
5. **Update or create** concept pages for every significant concept covered.
6. **Update** `wiki/index.md` — add the new source and any new pages.
7. **Append** to `wiki/log.md` — record what was ingested and what pages were touched.
8. **Update** `wiki/overview.md` if the new source materially changes the big picture.

Always tell the user how many pages were created/updated.

### Query workflow

When the user asks a question:

1. **Read** `wiki/index.md` to find relevant pages.
2. **Read** the relevant wiki pages (not raw sources — the wiki is your compiled knowledge).
3. **Synthesize** an answer with `[[wikilinks]]` to supporting pages.
4. If the answer is substantial and worth preserving, **offer to file it** as an analysis page.
5. **Append** to `wiki/log.md`.

### Lint workflow

When the user asks to lint/health-check the wiki:

1. Scan all wiki pages for:
   - **Contradictions** between pages
   - **Stale claims** superseded by newer sources
   - **Orphan pages** with no inbound links
   - **Missing pages** — concepts/entities mentioned in wikilinks but with no page yet
   - **Missing cross-references** — related pages that should link to each other but don't
   - **Data gaps** — topics where the wiki is thin and could use more sources
2. Report findings organized by severity.
3. Offer to fix mechanical issues (broken links, missing cross-refs) automatically.
4. Suggest new questions to investigate or sources to look for.
5. **Append** to `wiki/log.md`.

## Index format (`wiki/index.md`)

```markdown
# Wiki Index

## Sources
| Source | Date Added | Summary |
|--------|-----------|---------|
| [[Source - Title]] | YYYY-MM-DD | One-line summary |

## Entities
| Entity | Type | Sources |
|--------|------|---------|
| [[Entity Name]] | module/class/function/tool/hook/provider/integration/route/... | count |

## Concepts
| Concept | Sources |
|---------|---------|
| [[Concept Name]] | count |

## Analyses
| Analysis | Date | Question |
|----------|------|----------|
| [[Analysis - Topic]] | YYYY-MM-DD | The question it answers |
```

## Log format (`wiki/log.md`)

Each entry:
```markdown
## [YYYY-MM-DD] operation | Title
- Description of what happened
- Pages created: [[page1]], [[page2]]
- Pages updated: [[page3]], [[page4]]
```

## Omnideck domain reference

Key top-level modules to recognize as entities:
- `agents/` — agent profiles and the agent builder
- `sdk/` — core agent loop: providers, hooks, context management, events, skills, turn lifecycle
- `tools/` — all LLM-callable tools (browser, virtual_computer, memory, web, generation, integrations, desktop)
- `server/` — aiohttp app factory, API routes, React UI (`server/ui/`)
- `conversations/` — conversation persistence
- `integrations/` — supervisor, broker client, external service brokers (Gmail, Calendar, etc.)
- `tasks/` — autonomous goal/task runner
- `config/`, `settings.py` — config.yaml + environment overrides

Key concept areas to watch for:
- Agent loop and turn lifecycle
- Context compaction and summarization
- Hook system (pre/post turn hooks)
- Provider abstraction (OpenAI, Anthropic, OpenRouter, Ollama)
- Skill system
- Sandboxed code execution (Podman)
- Browser automation (Playwright)
- Tool schema generation and dispatch
- Integration supervisor and broker pattern
- Conversation and memory persistence

## Rules

1. **Never modify files in `raw/`.** Sources are immutable.
2. **Always update the index and log** after any operation.
3. **Link liberally.** If a page name exists or should exist, make it a wikilink.
4. **Create stubs for missing pages.** If you reference an entity/concept that doesn't have a page yet, create a minimal stub with a TODO note.
5. **Preserve attribution.** Every claim in the wiki should trace back to a source page.
6. **Flag contradictions.** If a new source contradicts existing wiki content, note it explicitly on both pages.
7. **Keep the overview current.** `wiki/overview.md` should always reflect the wiki's current state of knowledge.
8. **Be honest about gaps.** If the wiki doesn't cover something, say so rather than guessing.
9. **Dates are absolute.** Always use YYYY-MM-DD format. Today is 2026-06-22.
10. **Ask before large destructive operations.** Reorganizing, merging, or deleting pages — confirm with the user first.
