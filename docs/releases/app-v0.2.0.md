# omnideck app 0.2.0

This release keeps active agent work running across ordinary browser and
network interruptions, so returning to a conversation no longer loses work
that is still underway.

## Resumable agent runs

- Refreshing the page, waking the computer, or briefly losing the network no
  longer cancels an active agent run.
- Reopening the same conversation reconnects to its active run and replays the
  progress missed while the page was unavailable.
- While offline, omnideck preserves text and attachments in the composer,
  clearly marks the affected controls, and waits for connectivity before
  accepting messages, nudges, or stop requests.

Active runs remain tied to the running omnideck process. Restarting the
container does not resume a run that was active before the restart.
