# Connect your phone

You can join the call from your phone in two ways: the iPhone app, or Pointe's page in the phone's browser. Both reach
the daemon on your Mac through a second listener, on port 7443, that uses HTTPS. Your phone needs a private way to
reach that port. This page helps you choose one, pair the phone, and fix what goes wrong.

The iPhone app is **coming to the App Store: in review with Apple.** Until it is there, you build it from source
([The iPhone app](iphone-app.md#getting-the-app)), or use the page in the phone's browser, which needs nothing on the
phone.

## Which one should I use

| Route | Works when | You install | iPhone app | Phone browser | Guide |
|---|---|---|---|---|---|
| **Wi-Fi** | The phone and the Mac are on the same Wi-Fi, or the Mac is on the iPhone's hotspot. Only while both stay on it. | Nothing | Yes | Yes, after a certificate warning | [Wi-Fi](phone/wifi.md) |
| **Tailscale** | Anywhere both have internet | Tailscale on the Mac and the phone, one account | Yes | Yes, after a certificate warning | [Tailscale](phone/tailscale.md) |
| **Twingate** | Anywhere the phone's Twingate client is on | A Twingate network, a connector in Docker on the Mac (Colima works), the Twingate client on the phone | Yes | Yes, after a certificate warning, or with [a certificate the phone trusts](#a-certificate-the-phone-trusts) | [Twingate](phone/twingate.md) |
| **Cloudflare Tunnel with Access** | Anywhere, through a public name that only you can open | A Cloudflare account with a domain, `cloudflared` on the Mac | No | Yes | [Cloudflare](phone/cloudflare.md) |

- **Start with Tailscale** if you have no preference. It works away from home, needs no server, and is what the page
  recommends when it finds it (`pair.routes` in `pair.py` orders the route in use, then Tailscale, then a name you set
  up, then the Wi-Fi).
- **Wi-Fi** is the quickest to try, at home or with the Mac on the iPhone's hotspot. When either device leaves that
  network, or the Mac's address changes, pair again.
- **Twingate** suits a team that already runs it. It is the route the iPhone app was tested on with a real iPhone.
- **Cloudflare Tunnel** is for the phone's browser only. The iPhone app trusts only the Mac's own certificate, and a
  Cloudflare tunnel shows Cloudflare's certificate instead (see [why](phone/cloudflare.md#why-not-the-iphone-app)).

Each route keeps the same rule: the phone listener answers only HTTPS requests for the name you paired, and only from a
paired phone. The threat model for this path is in [SECURITY.md](../SECURITY.md#phone-access-experimental-off-by-default).

## Pairing

Pairing tells the phone where the Mac is and which certificate to trust, and gives the phone its own key. Choose the
route first (the guides above), then pair in one of these places.

### From the page

On the Mac, open Pointe's page: **Settings → Phone → Connect your phone**. The page lists the ways your phone can reach
this Mac (Tailscale, a name you set up such as a Twingate alias, the same Wi-Fi), marks one **Recommended**, and has a
field, "Or a name you set up (Twingate, a VPN)", with **Check**. Choose a route, then **Show the code**.

On the iPhone, scan the code in the Pointe app's pairing screen, and confirm the Mac it names (its address and the
start of its certificate's fingerprint). "Can't scan? Copy the link" copies the same `pointe://pair` link, which you can
paste in the app ("or paste the pointe:// link"). A `pointe://` link opened from the Camera, another app or a web page
pairs nothing: it only opens Pointe and says to scan the code inside the app, because any app can open such a link.
Replacing the Mac a phone is paired with asks for Face ID, and the old pairing stays until the new Mac answers. The page
turns to "Connected: &lt;phone&gt;" when the app has paired.

The code works once, for 5 minutes, and holds no lasting secret: the app checks the Mac's certificate first, then
trades the code for its own key (`phone_pairing.py`). Choosing a route that the current certificate does not cover
makes a new certificate, and the page says so first: every phone and machine paired before must pair again.

### From the Mac app

In the Mac app: **Call → Pair a Phone…**. It opens the same Phone sheet as the page, with the same routes, code and
buttons.

### From the terminal

`pointe pair` sets up the route and prints a QR code for the app. It also opens the code as a picture, because a chat
window cannot show the terminal's. Run by an agent (its output is not a terminal), `pair show` and `pair link` print no
secret: the codes open only as pictures on the Mac, so the phone key and the pairing secret stay out of the transcript.

| Command | Does |
|---|---|
| `pointe pair tailscale` | Listens on this Mac's Tailscale address, under its Tailscale name |
| `pointe pair wifi` | Listens on this Mac's address on the current Wi-Fi |
| `pointe pair host <name>` | Listens on `127.0.0.1` for a name you route yourself (Twingate, Cloudflare Tunnel) |
| `pointe pair show` | Shows the QR code again |
| `pointe pair link` | Prints the address that pairs a phone's browser |
| `pointe pair rotate` | Makes a new certificate (see below) |
| `pointe pair off` | Stops the phone listener |

The terminal's QR code carries the phone key itself, not a one-time code: show it only to your own phone, and scan it
inside the app, not with the Camera. After `pointe pair tailscale`, `wifi` or `host`, a running Pointe starts the
listener within a few seconds (otherwise at its next start).

### Rotate and unpair

- **Unpair one phone:** Settings → Phone on the page or in the Mac app, **Unpair** beside the phone, then click it again
  to confirm. Or, on the iPhone, the menu's **Unpair this phone**. That phone's call ends, and it needs a new code to
  come back.
- **Unpair all:** signs out every phone, including a phone browser paired with `pointe pair link`. That link stops
  working; `pointe pair link` prints the new one.
- **A new certificate:** `pointe pair rotate`. It signs out every phone, phone browser and paired machine at once (a
  running Pointe ends their calls and links within seconds), and makes a new pairing secret. Each must pair again, and
  a browser that trusted the old certificate must trust the new one. The command prints the steps for each paired
  machine. Use it when a phone is lost or a pairing code or link was seen by someone else.
- **Stop the listener:** `pointe pair off` signs out every phone, browser and machine the same way, and removes the
  certificate and the pairing secret. A Twingate connector started with `voice-connector` keeps running; stop it in
  Docker.
- **Deleting the app does not unpair it:** the pairing stays in the iPhone's Keychain and the Mac still takes its key.
  Unpair it on the Mac.

## In the phone's browser

The page works in the phone's browser like on the Mac, with nothing installed on the phone.

1. Set up a route (the guides above). In Claude Code, `/pointe:setup phone` walks you through it.
2. Run `pointe pair link` in your own terminal. It prints an address that holds a secret: send it only to your own
   phone (AirDrop or Notes), and open it once in the phone's browser. The browser keeps a pairing cookie, and the
   address it lands on can be added to the Home Screen.

The listener's certificate is made on your Mac, so the phone's browser warns about it on the first visit, except
through Cloudflare, which shows its own certificate. To make the phone trust this one name instead, see
[A certificate the phone trusts](#a-certificate-the-phone-trusts). Not measured: how each phone browser treats the
certificate on a first visit.

### A certificate the phone trusts

For a name routed to this Mac's loopback, such as a Twingate alias. Call audio is one WebSocket on the same HTTPS port,
so no UDP route is needed.

1. Set up the route ([Twingate](phone/twingate.md)), with an alias such as `phone.example.internal`.
2. Run `voice-remote setup phone.example.internal` from Pointe's `bin` folder (in a clone, `bin/voice-remote`). It makes a
   certificate authority that can vouch only for that one name, signs the listener's certificate with it, and destroys
   the authority's key.
3. AirDrop `~/.claude-voice/tls/pointe-ca.crt` to the phone, install it, and turn it on in Settings, General, About,
   Certificate Trust Settings.
4. Restart Pointe (`pointe restart`), then open the address from `pointe pair link` on the phone once.

The certificate is new, so a paired iPhone app must pair again, as after `pointe pair rotate`.

Remote requests need HTTPS, the configured name and the pairing cookie; anything else gets 403.

## Getting the app

The iPhone app is coming to the App Store: in review with Apple. Until then, build it from source with one command,
`pointe apps ios`. The steps, the free Apple Account and what to do when a build fails:
[The iPhone app](iphone-app.md#getting-the-app).

## The Mac stays awake during a call

While a call from the phone (or from the page on another device) is up and the Mac is on AC power, the daemon runs
`caffeinate -i -w <its pid>`, so the Mac does not idle-sleep and drop the call. It stops when the call ends or the Mac
goes to battery (checked every 5 seconds), and never runs on battery or when the power source cannot be read. Only idle
sleep is held off: the display may still sleep, and closing a laptop's lid still sleeps it. `/voice/status` says which,
in `keep_awake: {on, why}`.

## Troubleshooting

Start with the route's own guide, which has the checks for that network. These hold for every route.

| What you see | Why | Fix |
|---|---|---|
| The app says "Mac not reachable": "Can't reach your Mac at &lt;name&gt;. Is Twingate or Tailscale on? Is the Mac awake?" | The phone has no path to port 7443, the Mac sleeps, or the phone listener is off | Turn on the phone's Tailscale or Twingate, or join the Wi-Fi. Wake the Mac. Then check the listener: open `https://<name>:7443/voice/status` in the phone's browser. A certificate warning, then "This browser is no longer paired with the Mac…" or "forbidden", means the path works: pair the app again. No answer means the path is down: see the route's guide. |
| "Not paired": "This phone is no longer paired." | The phone was unpaired, or the certificate changed (`pointe pair rotate`, or another route was chosen) | Pair again: Settings → Phone → Connect your phone |
| "This code has expired or was already used." | The page's code lasts 5 minutes and works once | Press Connect your phone again and scan the new code |
| "Too many tries. Wait a minute, then scan the code again." | Too many wrong codes from this address | Wait a minute, then scan |
| "That code is not a Pointe pairing code." | The camera read another QR code | Scan the code on Pointe's Phone screen |
| The app worked yesterday on Wi-Fi, and not today | The Mac's Wi-Fi address changed, or one device left that network | Join the same network, then pair again with the Wi-Fi route |
| On Wi-Fi only, the app cannot reach the Mac | The app's Local Network access is off (iOS asks once, the first time) | iPhone: Settings, Privacy & Security, Local Network, turn Pointe on |
| The phone's browser shows "This browser is no longer paired with the Mac. On the Mac, run: pointe pair link…" | The browser has no pairing cookie, or Unpair all replaced the pairing secret | Run `pointe pair link` and open the new address once |
| The phone's browser shows "forbidden" | The address's name is not the one paired, or the request was not HTTPS | Open the exact address `pointe pair link` prints |
| The page says "Your phone cannot reach this Mac yet: Settings → Phone → Connect your phone." | No phone listener is set up | Set up a route, then pair |
| The page lists no route and says what to install | Neither Tailscale nor a Wi-Fi address was found, and no name was set | Install Tailscale on both, or join a Wi-Fi, or type a name you set up and press Check |
| The call drops when the Mac sleeps | On battery, or the lid closed | Use AC power and keep the lid open ([above](#the-mac-stays-awake-during-a-call)) |

