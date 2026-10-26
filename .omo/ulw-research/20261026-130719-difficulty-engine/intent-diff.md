# intent-diff.md — Difficulty Engine

| intent_id | expected truth | observed reality | diff | violated invariant | intent source | status |
|---|---|---|---|---|---|---|
| INT-01 | Wave 1 completable by a slow/beginner typist | Wave 1 can spawn 11-char words + fast mites; user reports can't clear level 1 | gap too small; word pool too long | wave-1 onboarding | user statement | violated |
| INT-02 | Difficulty rises with waves, never spikes unfairly | 30s flat waves; spawn_count=1+level/2; no wave table or events | no authored pacing | roguelike curve | genre intent | violated |
| INT-03 | Shop ranks bend the curve, never break it | Vitality/focus/chill/greed ~+18% max; untested vs curve | unknown interaction | balance | user requirement | unknown |
| INT-04 | Challenge adapts to measured typing skill | REF_WPM=40 fixed + rolling-WPM gap + mercy tiers exist | partial calibration only | adaptive intent | codebase reality | partial |
| INT-05 | Failure feels fair; near-death is readable | Leak=10dmg, mercy stuns exist; fail-soft unclear | need evidence | fairness | user requirement | unknown |
