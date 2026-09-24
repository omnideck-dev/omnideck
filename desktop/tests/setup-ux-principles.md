# Desktop setup UX principles

This is the canonical product and test contract for first-run setup and repair
on every supported operating system. Automated and manual desktop tests must
preserve these principles even when platform requirements force tasks to run in
a different order.

- OmniDeck is the primary setup surface and shows as much trustworthy progress
  as the underlying task provides.
- Native password, security, and permission prompts remain visible whenever the
  user must act. OmniDeck explains what is about to happen before waiting for
  that prompt.
- Podman, WSL, package-manager, and command-line installer windows remain hidden
  whenever they can run noninteractively. Hidden work must not wait on an
  invisible prompt.
- Progress is truthful: use real percentages and byte or item counts when they
  are available, `Waiting for approval` when the user must act, and an
  indeterminate state when no reliable measurement exists. Never synthesize a
  percentage or time estimate.
- Platform-specific task ordering is allowed when required by the operating
  system. The surrounding layout, language, progress treatment, retry behavior,
  and error presentation remain consistent.
- Retrying resumes at the failed stage and preserves completed work whenever it
  is safe to do so.
- Failures provide a clear next action and keep captured command or installer
  output inside the existing `Technical details` disclosure. Do not add a
  redundant diagnostic-log button or open a separate viewer.
- The Ready state contains the accepted completion copy and the
  `Open omnideck` button without a completed progress bar.

The clickable reference is the
[setup progress UX mockup](manual/setup-progress-mockup.html). Its platform tabs
document the accepted stage order and customer-facing states. The automated
[setup parity fixture](fixtures/electron-setup/setup-parity.json) keeps the
cross-platform DOM, state, and copy contract deterministic.
