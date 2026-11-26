# Connect over Tailscale

[Tailscale](https://tailscale.com/download) puts your computer and your phone on one private network, wherever each
has internet. Pointe listens on the computer's Tailscale address only, so nothing is open on the Wi-Fi or the internet.
This is the route the page recommends when it finds Tailscale.

You need: Pointe installed (`pointe` works in a terminal), and an iPhone with the Pointe app.

## Set it up

1. Install Tailscale on the computer and sign in:
   - **On a Mac:** the app from [tailscale.com/download](https://tailscale.com/download). Open it and sign in.
   - **On Linux:** the package for your distribution, from
     [Tailscale's Linux guide](https://tailscale.com/kb/1031/install-linux), then:

     ```
     sudo tailscale up
     ```

     It prints an address: open it in a browser and sign in.
2. On the iPhone, install **Tailscale** from the App Store, open it, and sign in with the **same account**.
3. On the computer:

   ```
   pointe pair tailscale
   ```

   It prints a QR code and the name the phone will use ("It connects to …").
4. Open the Pointe app, scan the QR code inside the app, and confirm the computer it names. The Camera app does not
   pair.

The page does the same as step 3: **Settings → Phone → Connect your phone**, choose **Tailscale**, then **Show the
code**.

## Check it

On the iPhone, with Tailscale on, open this in Safari, with the name from step 3:

```
https://<name>:7443/voice/status
```

Safari warns about the certificate first (Pointe made it on your computer); go past the warning. You should see
"This browser is no longer paired with the Mac. On the Mac, run: pointe pair link…". Pointe on your computer wrote
that line, so the route works. The app does not need this browser pairing.

## Name or address

Pointe uses both, for different things. It **listens** on the computer's Tailscale IPv4 address (`100.x.y.z`), and the
phone **connects by the MagicDNS name**, such as `my-laptop.example-tailnet.ts.net`. The certificate is made for that
name only, so the phone must be able to look it up: MagicDNS must be on. It is on by default for tailnets made since
October 2022; otherwise turn it on in the admin console's **DNS** page
([Tailscale's MagicDNS guide](https://tailscale.com/kb/1081/magicdns)). Both come from `tailscale status --json`
(`pointe/pair.py`).

## When it stops working

- **"Tailscale is not running on this Mac. Install it (https://tailscale.com/download), sign in, and retry."** →
  Tailscale is not installed, not running, or signed out on the computer. Open it and sign in (on Linux,
  `sudo tailscale up`).
- **"Tailscale has no name or address for this Mac yet."** → Tailscale is still connecting. Wait until it is
  connected, then run `pointe pair tailscale` again.
- **Safari says the server can't be found, or the app says "Can't find your Mac"** → Tailscale on the phone is off,
  signed in to another account, or MagicDNS is off. Open Tailscale on the iPhone, turn it on, check the account. Check
  MagicDNS ([above](#name-or-address)).
- **"Your Mac did not answer" or "Pointe is not answering", with Tailscale on both** → the computer sleeps, or Pointe
  does not run. Wake it; run `/pointe:voice` in a Claude Code session, or `pointe restart`. `pointe doctor` checks the
  route under "Phone".
- **The phone reaches other Tailscale devices, not this computer** → a Tailscale access rule blocks port 7443. Allow
  the phone to reach the computer on TCP 7443 in your tailnet's access controls.
- **The phone connects, then pairing fails, or the app says "Your Mac's certificate changed"** → the computer has a
  new certificate: after `pointe pair rotate`, a new route, a new Tailscale name, or a reinstall that removed Pointe's
  settings. Run `pointe pair tailscale` again and scan the new code.

The Tailscale name stays the same when the computer changes networks, so you pair once.

For the phone's browser instead of the app, run `pointe pair link` after step 3 and open the address once on the phone
([In the phone's browser](../phone.md#in-the-phones-browser)).
