---
target: app
type: added
area: providers
---

Tailscale Aperture can now be added as a provider using only its gateway URL.
OmniDeck discovers the models and supported API formats available to your
Tailscale identity automatically.

Agent inference controls now follow the selected model's discovered API and
capabilities. A GPT model routed through Aperture exposes Responses reasoning
controls, while a Claude model on the same gateway exposes Anthropic thinking
controls and model limits.

Thinking-capable models now expose the control they actually support: an
on/off switch, OpenAI reasoning levels, Anthropic thinking levels, or Ollama
GPT-OSS low/medium/high levels. Provider model metadata takes precedence, with
a single refreshable catalog supplying known-model fallbacks when an API omits
capabilities or limits.

Vision, context compaction, and conversation-title models now resolve their
own provider/model metadata as well. Their sampling settings default to Auto,
their output is capped appropriately for each role, and incompatible legacy
Ollama options are removed without overwriting customized values.

Agent context-window overrides are now shown only for Ollama, where they
configure the runtime. Cloud and gateway models use their detected fixed
capacity automatically; users control compaction timing with the threshold.
