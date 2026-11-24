# Connect over Tailscale

[Tailscale](https://tailscale.com/download) puts the Mac and the phone on one private network, wherever each has
internet. Pointe listens on the Mac's Tailscale address only, so nothing is open on the Wi-Fi or the internet. This is
the route the page recommends when it finds Tailscale on the Mac.

## Set it up

1. Install Tailscale on the Mac and on the iPhone, and sign in to both with the same account.
2. Pair. On the Mac, open Pointe's page: **Settings → Phone → Connect your phone**. Choose **Tailscale** (it shows the
   Mac's Tailscale name), then **Show the code**. In a terminal instead: `pointe pair tailscale`, then
   `pointe restart`.
3. On the iPhone, scan the code in the Pointe app and confirm the Mac it names. (The Camera does not pair: a link it opens only takes you to the app's scanner.)

For the phone's browser instead of the app, run `pointe pair link` after step 2 and open the address once on the phone
([In the phone's browser](../phone.md#in-the-phones-browser)).

## How it works

`pointe pair tailscale` asks the Tailscale app for this Mac's name (its MagicDNS name) and its IPv4 address
(`tailscale status --json`), makes a certificate for that name, and listens on the Tailscale address, port 7443
(`pointe/pair.py`). The phone connects by the name; the app trusts that one certificate, by its fingerprint. Tailscale needs
no account with Pointe and no server of yours.

## When it stops working

| What you see | Why | Fix |
|---|---|---|
| "Tailscale is not running on this Mac. Install it (https://tailscale.com/download), sign in, and retry." | The Tailscale app is not installed, not running, or signed out | Open Tailscale on the Mac and sign in |
| "Tailscale has no name or address for this Mac yet." | Tailscale is still connecting | Wait until it shows Connected, then pair again |
| "Can't find your Mac" or "Your Mac did not answer" on the phone | The phone's Tailscale is off, or signed in to another account | Open Tailscale on the iPhone, turn it on, check the account |
| "Your Mac did not answer" or "Pointe is not answering" while both are on Tailscale | The Mac sleeps, or the phone listener is off | Wake the Mac; on the page, Settings → Phone, check that Tailscale is "in use" |
| The phone reaches other Tailscale devices, not the Mac | A Tailscale access rule blocks port 7443 to the Mac | Allow the phone to reach the Mac on TCP 7443 in your tailnet's access controls |

The Tailscale name stays the same when the Mac changes networks, so you pair once.
