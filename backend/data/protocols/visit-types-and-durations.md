# Visit Types and Standard Durations

Every appointment length in the scheduler is derived from the visit type. Front
desk staff should never hand-enter a duration; if a listed duration is wrong for
the practice, change it in Settings so every future booking inherits the change.

| Visit type | Duration | New patient |
|---|---|---|
| Established patient follow-up | 15 minutes | No |
| New patient intake | 40 minutes | Yes |
| Annual physical | 30 minutes | No |
| Post-operative check | 20 minutes | No |
| Telehealth follow-up | 15 minutes | No |
| Procedure consultation | 30 minutes | No |

## Buffer time

The practice-wide buffer is applied after every appointment, not before. A
15-minute follow-up with a 5-minute buffer occupies 20 minutes of provider time
for conflict-checking purposes, but the patient is told 15 minutes.

## Changing a duration

Changing a visit type's duration affects future bookings only. Appointments
already on the calendar keep the duration they were booked with, so a change
never silently shortens a scheduled visit.
