# Connect over Twingate

[Twingate](https://www.twingate.com) gives your phone a private name for your computer, such as
`pointe.<you>.internal`, wherever the phone has internet. A Twingate connector runs on the computer, in Docker, and
forwards that name to Pointe's phone listener on port 7443. Nothing is open on the Wi-Fi or the internet. The steps
are the same on a Mac and on Linux, except step 2.

You need: Homebrew on a Mac, or Docker on Linux; Pointe installed (`pointe` works in a terminal); an iPhone with the
Pointe app.

## Set it up

### 1. A Twingate network

- **Your company already uses Twingate:** ask its admin to invite you and to let you add a remote network, or to do
  steps 3 and 4 for you. Your network's name, such as `example.twingate.com`, is in Twingate's welcome email.
- **No network yet:** sign up at [twingate.com](https://www.twingate.com). You choose the network's name during the
  sign-up. The plans are on [Twingate's pricing page](https://www.twingate.com/pricing).

### 2. Docker

**On a Mac**, with Homebrew:

```
brew install colima docker
limactl --version
```

The second command must print **2.3.0 or later**. Colima runs Docker in a Lima virtual machine, and Lima before 2.3.0
let only 10 TCP connections at a time start through that machine's network: the phone then failed to connect, or the
call stalled. Lima 2.3.0 raised the limit to 128 (it ships
[gvisor-tap-vsock 0.9.0](https://github.com/containers/gvisor-tap-vsock/pull/698)). If the version is older:

```
brew upgrade lima
colima stop
```

Then start Docker:

```
colima start
```

Colima does not start by itself after a restart of the Mac. To start it now and at every login, use
`brew services start colima` instead.

**On Linux**, install Docker Engine and check that `docker ps` works without `sudo`. Or use Twingate's own Linux
package instead of Docker: in step 3, choose **Linux** instead of **Docker** and run the command the console shows
([Twingate's guide](https://www.twingate.com/docs/connectors-on-linux)). That command holds the tokens, so it goes into
your shell history; Pointe's helper below keeps them out.

### 3. The connector

1. In the Twingate admin console, click **Network**. Next to **Remote Networks**, click **Add**, choose a location, and
   name it after this computer.
2. In that remote network, click **Deploy Connector** and choose **Docker**. Generate the tokens (Twingate asks you to
   sign in again). Copy the `docker run` command the console shows. Do not paste it in a terminal: it holds the
   tokens.
3. Run Pointe's connector helper:

   ```
   "$(dirname "$(tail -n 1 ~/.local/bin/pointe | cut -d' ' -f2)")/voice-connector"
   ```

   It reads the command from the clipboard, keeps the tokens in `~/.claude-voice/twingate-connector.env` (only you can
   read it), and starts the connector with `--restart=unless-stopped`. On Linux it shares the computer's network
   (`--network host`). Over SSH, with no clipboard, it asks you to paste the command: paste it, press Enter, then
   Ctrl-D. In a clone of the repository, the helper is `bin/voice-connector`.
4. `docker ps` lists the connector (`twingate-…`), and the console shows it as connected after a few seconds.

### 4. The resource

In the admin console, click **Network**, then **Add Resource**, in the remote network from step 3:

| Field | Value |
|---|---|
| Label | `Pointe` |
| Address | On a Mac: `host.docker.internal` (the Mac, as the connector's container sees it). On Linux: `127.0.0.1` |
| Alias | `pointe.<you>.internal`, a name of your own. Not `.local`, which [Twingate advises against](https://www.twingate.com/docs/resource-aliases) |
| Ports | TCP 7443 only. Block UDP |
| Access | A group with only you in it. The **Everyone** group gives it to every user of the network ([groups](https://www.twingate.com/docs/groups)) |

### 5. Pair

1. On the computer:

   ```
   pointe pair host pointe.<you>.internal
   ```

   It prints a QR code.
2. On the iPhone, install **Twingate** from the App Store. Open it, type your network's name, tap **Join Network**,
   then **Sign in to Connect** ([Twingate's iOS guide](https://www.twingate.com/docs/ios)).
3. Open the Pointe app, scan the QR code inside the app, and confirm the computer it names. The Camera app does not
   pair.

The page does the same as step 1: **Settings → Phone → Connect your phone**, type the alias in "Or a name you set up
(Twingate, a VPN)", press **Check**, then **Show the code**. It may say "This Mac can't look it up": expected, as the
alias often resolves only on the phone.

## Check it

On the iPhone, with Twingate on, open this in Safari, with your alias in place of `<alias>`:

```
https://<alias>:7443/voice/status
```

Safari warns about the certificate first (Pointe made it on your computer); go past the warning. You should see
"This browser is no longer paired with the Mac. On the Mac, run: pointe pair link…". Pointe on your computer wrote
that line, so the route works. The app does not need this browser pairing.

## When it stops working

On the computer, `pointe doctor` checks the paired route under "Phone".

- **Safari says the server can't be found, or the app says "Can't find your Mac"** → Twingate on the phone does not
  handle the name. In the phone's Twingate app: it is connected, and the resource is listed. Turn off any other VPN.
  Turn off iCloud Private Relay (Settings, your name, iCloud, Private Relay). A new alias sometimes resolves only after
  you quit and reopen the Twingate app.
- **It works on the computer, not on the phone** → the phone signed in with another account or network, or that
  account is not in the resource's group. Check both in the admin console.
- **"Your Mac did not answer"** → the connector is down. On a Mac: `colima status`, then `colima start` (the connector
  comes back by itself). Then `docker ps` lists it, and the console shows it connected. If not, read
  `docker logs <the connector's name>`, or run the helper again; for new tokens, copy a new command first.
- **The connection stalls, or works only on the second or third try, on a Mac** → `limactl --version`. Below 2.3.0:
  `brew upgrade lima`, `colima stop`, `colima start`.
- **"Pointe is not answering"** → Pointe does not run on the computer. Run `/pointe:voice` in a Claude Code session,
  or `pointe restart`.
- **The phone connects, then pairing fails, or the app says "Your Mac's certificate changed"** → the computer has a
  new certificate: after `pointe pair rotate`, a new route, or a reinstall that removed Pointe's settings. Run
  `pointe pair host pointe.<you>.internal` again and scan the new code.
- **On Linux, you started the console's `docker run` command yourself** → that connector sits on Docker's bridge and
  cannot reach `127.0.0.1`. Run `pointe pair host pointe.<you>.internal --listen docker`, and set the resource's
  address to the bridge address it prints (usually `172.17.0.1`). Or remove that container and use the helper.
- **Safari reaches the address and the app does not** → pair the app again.

## How it works

`pointe pair host <alias>` makes a certificate for the alias and listens on `127.0.0.1`, port 7443
(`pointe/pair.py`). The phone's Twingate client sends the alias's connections to the connector, which forwards them to
that port. The app trusts the computer's certificate by its fingerprint, end to end: Twingate carries the connection
and does not decrypt it.

For the phone's browser instead of the app, run `pointe pair link` after step 5 and open the address once on the phone.
To avoid the certificate warning, make the phone trust this one name:
[A certificate the phone trusts](../phone.md#a-certificate-the-phone-trusts).

To remove the connector: `pointe pair off` stops Pointe's listener only. Then `docker rm -f <the connector's name>`,
delete `~/.claude-voice/twingate-connector.env`, and remove the connector in the console.
