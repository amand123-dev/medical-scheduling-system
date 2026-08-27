# Waitlist and Cancellation Policy

## When a cancellation happens

Cancelling an appointment immediately triggers the backfill engine. The freed
slot is matched against waiting patients and offered to the best-scoring
candidate. Staff do not need to call down a list manually.

## How candidates are ranked

Candidates are filtered first, then scored. A patient must clear every filter to
be considered:

- The requested visit type must fit inside the freed slot's duration
- The waitlist entry must be for the same provider
- The slot must fall inside the patient's stated availability window

Surviving candidates are scored as `w1 x priority + w2 x wait_time - w3 x
decline_risk`. The three weights are configurable in Settings; they are not
hard-coded, because a paediatric practice and a surgical practice weigh urgency
and waiting time differently.

## The hold window

An offer is held for a configurable window, 30 minutes by default. If the
patient does not respond within the window, the offer expires and cascades to
the next-best candidate automatically. An expired offer is not a decline and
does not count against the patient's decline risk.

## Declines

A decline cascades the slot to the next candidate immediately. Declines slightly
lower a patient's score on future offers so that repeatedly-unavailable patients
do not block a slot, but a decline never removes a patient from the waitlist and
never affects their priority for a directly-booked appointment.
