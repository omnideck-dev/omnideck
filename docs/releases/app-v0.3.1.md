# omnideck app 0.3.1

## Fixed

- **Agents:** Stopping parallel sub-agents now waits for every child's cleanup before ending the run, keeping their completion events in conversation history and preventing the Agent Network from leaving stopped agents marked as running.
- **Routines:** Deleting a running routine or an individual run now stops its active tasks and sub-agents before removing their records, preventing work from continuing after deletion. Deleting one run leaves other runs active.
