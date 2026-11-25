# Connect over Twingate

[Twingate](https://www.twingate.com) gives the phone a private name for the Mac, wherever the phone has internet. A
Twingate connector runs on the Mac, in Docker, and forwards that name to Pointe's listener on `127.0.0.1`. Nothing is
open on the Wi-Fi or the internet. The iPhone app was tested on a real iPhone over this route.

You need a Twingate network you can administer, Docker on the Mac (this guide uses Colima), and
the Twingate client on the iPhone, signed in.

On a Linux hub the connector shares the machine's network, or sits on Docker's bridge with
`pointe pair host <alias> --listen docker`: [Linux](../linux.md#reach-it-from-other-devices).

## Set it up

### 1. Docker on the Mac

With Homebrew:

```
brew install colima docker
colima start
```

Colima does not start by itself after a reboot. To start it now and at every login instead, use
`brew services start colima`. Docker Desktop works too.

### 2. The connector

1. In the Twingate admin console, add a remote network for the Mac, then a connector in it, and choose Docker. The
   console shows a `docker run` command with the connector's tokens.
2. Copy that command, then run Pointe's `voice-connector`. It reads the command from the clipboard, keeps the tokens in
   a file only you can read (`~/.claude-voice/twingate-connector.env`), and starts the container with
   `--restart=unless-stopped`. The tokens never reach a command line or your shell history.

   `voice-connector` is in the `bin` folder of the plugin: the last line of `~/.local/bin/pointe` names that folder.
   In a clone, it is `bin/voice-connector`.

3. In the console, the connector shows as connected after a few seconds. On the Mac, `docker ps` lists it.

### 3. The resource

In the Twingate console, add a resource in the same remote network:

| Field | Value | Why |
|---|---|---|
| Address | `host.docker.internal` | The Mac itself, as the connector's container sees it |
| Alias | a name of your own, such as `pointe.example.internal` | The name the phone uses, and the name the certificate is made for |
| Ports | TCP 7443 only | Pointe's phone listener, and nothing else on the Mac |
| Access | only you | Anyone with access can reach the listener; pairing still guards it |

### 4. Pair

1. On the iPhone, open the Twingate client and sign in.
2. On the Mac, open Pointe's page: **Settings → Phone → Connect your phone**. In "Or a name you set up (Twingate, a
   VPN)", type the alias and press **Check**, then choose it and **Show the code**. In a terminal instead:
   `pointe pair host pointe.example.internal`, then `pointe restart`.
3. On the iPhone, scan the code in the Pointe app and confirm the Mac it names. (The Camera does not pair: a link it opens only takes you to the app's scanner.)

The page may say "This Mac can't look it up, so Pointe can't check it." That is expected: a Twingate alias often
resolves only on the phone. Use it anyway.

For the phone's browser instead of the app, run `pointe pair link` after step 2 and open the address once on the phone.
To avoid the certificate warning, make the phone trust this one name:
[A certificate the phone trusts](../phone.md#a-certificate-the-phone-trusts).

## How it works

`pointe pair host <alias>` makes a certificate for the alias and listens on `127.0.0.1`, port 7443 (`pointe/pair.py`). The
phone's Twingate client resolves the alias and sends the connection to the connector on the Mac, which forwards it to
the listener. The app trusts the Mac's certificate by its fingerprint, end to end: Twingate carries the connection and
does not decrypt it.

## When it stops working

The app says "Can't find your Mac" or "Your Mac did not answer", with the alias it tried. On the Mac, the page warns
"&lt;alias&gt; does not reach this Mac" beside the code, and `pointe doctor` says the same under "Phone". Check in this
order.

| Check | Why | Fix |
|---|---|---|
| Docker runs on the Mac: `colima status` (or `docker ps` answers) | Colima stops when the Mac restarts, and the connector with it. The phone cannot connect until it runs again. | `colima start`. The connector comes back by itself (`--restart=unless-stopped`). To avoid this after the next reboot: `brew services start colima`. |
| The connector container runs: `docker ps` lists it | It was stopped, or its tokens were revoked in the console | Start it again with `voice-connector`; for new tokens, copy a new command from the console first |
| The console shows the connector as connected | The Mac has no internet, or the connector cannot reach Twingate | Fix the Mac's network; read `docker logs <the connector's name>` |
| The phone's Twingate client is on and signed in | The alias resolves only through the client | Turn the client on |
| The alias resolves on the phone | A new alias sometimes does not resolve until the client restarts | Quit and reopen the Twingate client on the phone, or sign out and in |
| The resource allows TCP 7443, for you | Another port, or no access, blocks the connection | Edit the resource in the console |
| The listener answers: open `https://<alias>:7443/voice/status` in Safari on the phone | A certificate warning, then "This browser is no longer paired with the Mac…" or "forbidden", means Twingate works | If Safari reaches it and the app does not, pair the app again. If Safari can't reach it either, the problem is in the rows above. |
| Pointe runs on the Mac, with the phone listener on | The listener starts with Pointe | On the page, Settings → Phone: the alias is "in use". Or run `pointe pair host <alias>`, then `pointe restart`. |

`pointe pair off` stops Pointe's listener and leaves the connector running. To remove the connector too, stop and
delete its container (`docker rm -f <the connector's name>`), delete `~/.claude-voice/twingate-connector.env`, and
remove the connector in the console.
