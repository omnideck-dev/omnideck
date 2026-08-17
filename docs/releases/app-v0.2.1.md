# omnideck app 0.2.1

This patch prevents scheduled routines from leaving browser processes behind
after their work finishes.

## Fixed

- Scheduled routines now release browser resources after success, failure,
  cancellation, or setup errors.
- Tasks that do not stop during graceful shutdown are cancelled and cleaned up
  instead of continuing to hold browser resources.

These changes prevent completed or stalled routines from accumulating excess
CPU and memory use. Interactive conversation browsers continue to persist
across turns as before.
