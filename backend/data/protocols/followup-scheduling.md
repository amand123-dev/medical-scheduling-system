# Protocol-Driven Follow-Up Scheduling

Some visit types require a follow-up to be scheduled before the patient leaves.
The scheduler surfaces this as a prompt at check-out; it does not book anything
automatically, because the follow-up window depends on what happened in the
visit.

## Required follow-up windows

| Visit type | Follow-up required | Window |
|---|---|---|
| Post-operative check | Yes | 10–14 days after the procedure |
| New patient intake | Yes | Within 90 days |
| Procedure consultation | Yes | Within 30 days |
| Annual physical | No | Next annual, ~12 months |
| Established patient follow-up | Provider's discretion | — |
| Telehealth follow-up | Provider's discretion | — |

## Post-operative follow-up

Post-operative checks are scheduled 10 to 14 days after the procedure date. If
no slot is available in that window with the operating provider, book with any
provider in the same specialty rather than pushing past 14 days. A post-op check
outside the window should be flagged to the provider before booking.

## Missed follow-ups

If a required follow-up is never booked, the appointment appears on the
outstanding-follow-up list on the dashboard. This is a scheduling gap to close,
not a patient behaviour to record.
