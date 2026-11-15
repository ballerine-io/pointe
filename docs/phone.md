# Phone access

## The iPhone app

On the Mac, open Pointe's page: Settings → Phone → **Connect your phone**. The page lists the ways your phone can
reach this Mac (Tailscale, a name you set up such as a Twingate alias, the same Wi-Fi), recommends one, and shows a QR
code. Point the iPhone's Camera at it and tap "Open in Pointe" (or scan it in the app). The page turns to "Connected:
<phone>" when the app has paired. The code works once, for 5 minutes; the app gets its key from the Mac over the
certificate it checks. Each phone gets its own key: connecting another phone keeps the ones already paired, **Unpair**
on a phone signs out that phone only, and **Unpair all** signs out every one. A phone paired with `pointe pair` before
this keeps working; it shows as "Paired phone" until the app reports its name. If no way works, the page says what to
install.

Or, in a terminal, pick how the phone reaches the Mac, then scan the QR code in the app:

| Command | When |
|---|---|
| `pointe pair host <name>` | Twingate, a VPN, or a tunnel you route yourself to this Mac's port 7443 |
| `pointe pair tailscale` | the Mac and the phone are both on Tailscale |
| `pointe pair wifi` | same Wi-Fi only; pair again when the address changes |

With Twingate: a Connector on this Mac (Docker or Colima), a resource for the Mac with an alias such as
`pointe.example.internal`, TCP 7443, access for you only. Then `pointe pair host pointe.example.internal`. If the app says
"Mac not reachable" while Safari on the phone reaches `https://<name>:7443/voice/status` (a warning, then "Forbidden"),
pair again. If Safari can't reach it either, restart the Twingate client: new aliases sometimes don't resolve until then.

## The Mac stays awake during a call

While a call from the phone (or from the page on another device) is up and the Mac is on AC power, the daemon runs
`caffeinate -i -w <its pid>`, so the Mac does not idle-sleep and drop the call. It stops when the call ends or the Mac
goes to battery (checked every 5 seconds), and never runs on battery or when the power source cannot be read. Only idle
sleep is held off: the display may still sleep, and closing a laptop's lid still sleeps it. `/voice/status` says which,
in `keep_awake: {on, why}`.

## What stays on the Mac

The app does what the page does, with one deliberate exception: the voice model's full context is shown only on the
Mac. The page's "What the voice holds" lists the messages of the call's context; the app shows only the token count
(Sessions sheet), and the phone's key is refused `/voice/context`.

## Alerts and the Apple Watch

Menu → Alerts. "Alerts on this iPhone" posts a notification when a session needs you and the app is not on screen; iOS
mirrors it to an Apple Watch on your wrist while the iPhone is locked. There is no push server, so this works while the
app is alive: open, or in the background with the call up. With the call down and the app in the background, iOS checks
only when it grants a Background App Refresh (rarely, never in Low Power Mode, never after you swipe the app away).
"Approve from notifications" (shared with the page's Settings, off by default) adds Approve to a notification for a
request Pointe can read out; it needs an unlocked iPhone or a watch on the wrist instead of Face ID.

To check by hand on a real iPhone and watch (the simulator has no watch; not yet done on real devices):
1. Alerts on, call up, lock the iPhone, wear the watch. A request arrives: the watch taps, and shows the session and the
   read-out form, with Deny and Approve.
2. Approve on the watch: the session gets it; the iPhone notification is gone.
3. Answer one on the Mac instead: the watch notification disappears within a second or two.
4. Take the watch off (locked): Approve asks to unlock it first.
5. An unreadable request (`python3 -c …`): the watch shows only "Bash: open Pointe to see the exact request", Deny only.

## The browser page (older way)

The browser page over Twingate. Call audio is one WebSocket on the same HTTPS port, so no UDP resource is needed.

1. Twingate console: a remote network with a Connector running in Docker (Colima) on this Mac; a resource
   `host.docker.internal`, alias `phone.example.internal`, TCP 7443, access for you only.
2. Done on this Mac: `bin/voice-remote setup phone.example.internal`; the daemon serves HTTPS on 127.0.0.1:7443.
3. AirDrop `~/.claude-voice/tls/pointe-ca.crt` to the phone; trust it in Settings > General > About >
   Certificate Trust Settings. The CA can only vouch for that one name, and its key is destroyed after signing.
4. `bin/voice-remote link` in your own terminal (it prints the pairing secret); open the link on the phone once.

Remote requests need HTTPS, the configured name, and the pairing cookie; anything else gets 403.
