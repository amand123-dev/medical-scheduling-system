# No-Show Risk and Reminder Escalation

## What the risk score is

The no-show risk score is the patient's historical no-show ratio: no-shows
divided by total completed-or-missed appointments. It requires at least three
prior appointments; below that the patient shows as "insufficient data" and
receives standard reminders only.

The score is a scheduling signal, not a clinical or character judgement.

## Risk buckets

| Bucket | Threshold | Outreach |
|---|---|---|
| Low | below 0.2 | Standard SMS reminder |
| Medium | 0.2 to 0.5 | Standard SMS plus a follow-up email |
| High | 0.5 and above | Standard SMS, follow-up email, and a staff call |

Thresholds are configurable in Settings.

## What escalation means

Escalation adds outreach. It never removes access. A high-risk patient is not
deprioritized on the waitlist, is not blocked from booking, is not double-booked
against, and is not required to prepay. The correct response to a high risk
score is a phone call asking whether the patient needs help getting to the
appointment — transport, timing, or a telehealth alternative.

Staff should not discuss the risk score with the patient as a score. It exists
to route staff attention, not to be reported back.
