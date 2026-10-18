---
title: Using Omnideck at Work — A Guide for IT and Security Reviewers
type: guide
tags: [security, it, compliance, one-pager, work, marketing, faq]
created: 2026-09-23
updated: 2026-10-18
sources: ["README.md", "[[Credential Brokering]]", "[[Provider Abstraction]]", "[[Sandboxed Code Execution]]"]
---

# Using Omnideck at Work

**A one-page answer for the questions your IT team or CTO will ask before you use an AI assistant for work.**

## The short version

Omnideck is a self-hosted AI assistant that runs entirely on hardware your company controls — a laptop, a workstation, or an internal server. There is no telemetry. Nothing about your usage, your prompts, or your data is sent to us, because there is no "us" in the runtime path at all: it's open-source software you run yourself, the same way you'd run a local database or a dev container.

If your organization already trusts you to run Docker containers and use an LLM API key, you already have everything Omnideck needs.

## What it actually is

Omnideck is a **wrapper around whatever LLM your organization has already approved** — not a new AI vendor to vet. It doesn't ship its own model or its own inference service. You point it at:

- An LLM your company already has a contract with (Anthropic, OpenAI, Azure OpenAI, or any OpenAI-compatible endpoint), or
- A model running entirely on your own hardware via Ollama, with no external API calls at all.

If your company's answer to "can I use Claude/ChatGPT for work" is already yes, Omnideck doesn't introduce a new data-handling question — it's the same approved model, with a better interface and local tools around it. If your company requires local-only inference, Omnideck supports that too, and at that point no prompt or response ever leaves the machine it's running on.

## The five things a security review usually asks about

**1. Open source (Apache 2.0).**
The full source is available for review under the Apache License 2.0 — a standard, OSI-approved permissive license, not a source-available license with usage restrictions. Nothing is a black box; your security team can read exactly what the agent can and cannot do before anyone runs it, rather than taking a vendor's word for it.

**2. Containerized.**
Omnideck runs as a single container image. It doesn't install anything into the host OS, doesn't require elevated host privileges to operate, and can be stopped, removed, or rebuilt cleanly. State (conversations, memory, settings) lives in one dedicated host directory (`~/Omnideck`) that's bind-mounted into the container — the container only ever sees that one directory, so the agent's filesystem is isolated from the rest of your machine by the container boundary itself, and it can't reach or modify local files outside what you've explicitly exposed to it. `omnideck uninstall` can back up and delete that directory for you.

**3. Secrets never reach the model.**
This is the part worth walking your CTO through directly. API keys and OAuth tokens (for the LLM provider itself, and for any connected integration like email or calendar) are held by a separate, privilege-separated supervisor process — not the process that talks to the LLM. When the agent needs to call an API, the request is proxied through the supervisor over a local Unix socket, and the supervisor attaches the real credential on the way out. The application code the LLM's tool calls run through never holds a decrypted key in memory. Concretely: **even if the LLM tried to exfiltrate a credential, or the agent process were fully compromised, there is no decrypted secret sitting in a place either could read.** This is a stronger isolation guarantee than most SaaS AI tools offer, where your API key is typically just an environment variable next to your application code.

**4. No telemetry.**
There is no analytics SDK, no usage tracking, and no phone-home behavior anywhere in the codebase — that's a verifiable claim, not a policy promise, since the source is open. Nothing about how you use it is collected, by us or anyone else.

**5. Runs locally, with any model you like.**
The whole system is a container plus a Go CLI to manage it. It runs on your machine or your infra, under your network policy, behind your firewall. Swapping models — cloud to local, one vendor to another — is a config change, not a re-architecture. That means adopting Omnideck is not an additional-vendor decision; it's a decision to run an open-source client against a model your organization has already approved.

## What this means in practice

- **For IT:** it's a container you can inspect, scan, and remove like any other internal tool. It doesn't require a new SaaS vendor review, a new DPA, or a new data-residency conversation if you're already using local or already-approved models.
- **For a CTO or security lead:** the credential-isolation design (point 3) is the thing worth a closer look — it's arguably tighter than the ambient-API-key pattern most internal tools use today.
- **For you:** you can point people at this page instead of re-explaining the architecture in a Slack thread. If the answer to "can I run this" is still no, the follow-up is a narrow one — usually "can we run it against our already-approved model" rather than "can we approve an entirely new AI product."

## FAQ

**What license is this actually under? Any restrictions?**
Apache License 2.0 — the same permissive, OSI-approved license used by Kubernetes, Kafka, and most enterprise-grade OSS. No field-of-use restrictions, no "can't compete with us" clause. Your legal team can approve it the same way they'd approve any other Apache-licensed dependency.

**Who supports this if something breaks? Is there a vendor SLA?**
No. Omnideck is maintained by its two creators (Larry Foulkrod and Ron Northcutt), not a company with a support contract. There's no SLA, no ticket queue, no guaranteed response time — support is open-source-project support (issues, patches, `omnideck update` for fixes). If your organization requires a vendor support agreement for any tool touching work data, say so up front; that's a real gap, not something this page can paper over.

**Does the web UI require a login?**
No — there's no built-in authentication in front of the app itself. The access boundary is whatever network exposure you give it: by default it's bound to localhost on your own machine, which is the intended deployment. If you ever put it on a shared network or server, you're responsible for putting your own access control in front of it (a reverse proxy with auth, a VPN, a firewall rule) — the same way you would for any other unauthenticated local dev tool.

**Does anything ever leave my machine?**
Only traffic to the LLM provider (and any integrations, like Gmail or Calendar) that *you* configure — nothing to Omnideck's creators, ever, and no telemetry. If you configure a fully local model via Ollama, there is no external network call at all. If you configure a cloud model, the only egress is to that provider's API, using the credentials it already has — the same traffic that would exist if you called that API directly yourself.

**Can the agent browse the web? Is that an exfiltration risk?**
Yes, one of its tools drives a real, persistent-session browser (Playwright/Chrome) to whatever page it needs. That's a capability, not a hidden one — it behaves like giving an employee's script the ability to open a browser tab. Egress from it follows the same network policy as any other browser on that machine; if your org restricts outbound traffic at the firewall or proxy level, that restriction applies here too. There's nothing browser-tool-specific to carve out.

**How are stored credentials (API keys, OAuth tokens) protected at rest?**
Encrypted with AES-256-GCM in a vault directory, decrypted only inside the separate supervisor process described above. The master key itself is protected by OS file permissions (owner-only, mode 0600) rather than a hardware security module — solid for a self-hosted single-machine tool, but worth knowing precisely rather than assuming enterprise-KMS-grade protection.

**Does Omnideck have SOC 2 / ISO 27001 / HIPAA certification?**
No, and structurally it can't — those certifications apply to a vendor processing your data on their infrastructure, and there is no vendor in this data path. Self-hosting means your organization's existing infrastructure controls are what apply, the same as for any other self-hosted open-source tool you already run (a database, a CI runner, an internal dashboard).

**Where does my data actually live, and how do I get rid of it?**
Everything — conversations, memory, settings — lives in `~/Omnideck`, a single host directory bind-mounted into the container. That's a deliberate isolation boundary, not just a storage detail: the container (and the agent running inside it) only ever sees that one directory, so it can't read, write, or bypass files elsewhere on your system beyond what you've explicitly exposed to it. There's no remote copy to separately request deletion of — `omnideck uninstall` can back up and then delete that directory in one step.

