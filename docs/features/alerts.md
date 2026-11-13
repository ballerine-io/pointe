# Wrist approvals and desktop alerts

A session needs you: your watch taps, it shows what the session wants to run, and you deny or, if you allow it, approve
from the wrist. On the desktop, the same event is a notification that brings the page forward.

This is version 1: iPhone notifications that iOS mirrors to an Apple Watch, and browser notifications on the Mac. There
is no native watchOS app yet. The rules live in `alerts.py`; `daemon.py` builds the attention list from them and checks
an Approve that comes from a notification.

## Use it

- **Page:** Settings → Alerts → "Desktop alerts" (per browser; the browser asks for permission when you tick it). An
  item that appears while the tab is hidden becomes one notification. It closes when the item is answered or the tab is
  shown; a click brings the page forward. Approving stays a click on the card.
- **iPhone:** Menu → Alerts → "Alerts on this iPhone" (off until you turn it on). The app posts a local notification
  when a session needs you and the app is not on screen, and withdraws it when the item is answered. iOS mirrors it to
  a watch on your wrist while the iPhone is locked.
- **"Approve from notifications"** (one setting for both clients, off by default; the app asks for Face ID to turn it
  on) adds Approve to a notification.

What raises an alert: a permission request, a session that ended its turn waiting on you, a raised hand in a
[meeting](meeting-mode.md), a [conflict](conflict-alarm.md), and a scheduled [briefing](briefings.md) that is ready.

## Rules

- **What a notification shows** is the read-out form of a request (the read-out allowlist), never its full text or the
  model's description. That text may hold a secret. A request that cannot be read out shows only
  `"<Tool>: open Pointe to see the exact request"`. A credential-like value is never shown or said.
- **Approve from a notification** is offered only when the setting is on and the request is one Pointe can read out:
  exactly what a spoken yes could approve. It needs an unlocked iPhone, or a watch on the wrist, instead of Face ID. The
  daemon accepts it (`via: "notification"`) only for that request's id. Anything else needs the app (Face ID) or the page.
- **Deny** is always offered for a permission, and is the first action.
- A stale request answers "Already answered"; a refused Approve answers "Approve it in the app"; anything else answers
  "Mac not reachable", and the notification is posted again on the next check.

## Limits

- **No push server.** The phone learns about a request from its own status checks. This works while the app is alive:
  open, or in the background with a call up. With the call down and the app in the background, iOS checks only when it
  grants a Background App Refresh: rarely, never in Low Power Mode, never after you swipe the app away.
- Checked by hand on a real iPhone and watch (the simulator has no watch); the steps are in [phone.md](../phone.md).
- Not built: per-event switches, sound and lock-screen preview settings (iOS's own settings cover them), Touch ID on the
  page, and the Time Sensitive entitlement.

## API

- Status `attention: [{id, kind: permission|question|hand|conflict|briefing, session?, request_id?, title, body, text,
  approvable, at}]`. `title` and `body` are what a notification may show. `approvable`: a notification may offer
  Approve. A `question` is a session that ended its turn waiting on you, id `question:<session>:<since>`.
- `POST /voice/approve` takes `via: "notification"`: an Allow is refused (403) unless the setting is on and the request
  is `approvable`; a stale `request_id` is 409. Deny needs neither.
- `POST /voice/attention {id}` dismisses one item for this call.
- Pref `alerts.watch_approve` (default false) in `GET/POST /voice/prefs`.
