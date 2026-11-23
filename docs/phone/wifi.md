# Connect over Wi-Fi

The phone reaches the Mac's address on the network they share. You install nothing. It works only while both devices
stay on that network, and until the Mac's address changes. For a route that works away from home, use
[Tailscale](tailscale.md).

Two networks work:

- **The same Wi-Fi.** The Mac and the phone are on one Wi-Fi network, at home or in an office that lets devices reach
  each other.
- **The iPhone's hotspot.** Turn on Personal Hotspot on the iPhone and join it from the Mac. The phone then reaches the
  Mac on the hotspot's network, with no other Wi-Fi around.

## Set it up

1. Put the Mac and the phone on the same network (one of the two above).
2. Pair. On the Mac, open Pointe's page: **Settings → Phone → Connect your phone**. Choose **Same Wi-Fi** (it shows the
   Mac's address), then **Show the code**. In a terminal instead: `pointe pair wifi`, then `pointe restart`.
3. On the iPhone, scan the code with the Camera and tap "Open in Pointe", or scan it in the app.
4. The first time, iOS asks whether Pointe may find and connect to devices on your local network. Allow it: the
   Wi-Fi route needs it.

For the phone's browser instead of the app, run `pointe pair link` after step 2 and open the address once on the phone
([In the phone's browser](../phone.md#in-the-phones-browser)).

## How it works

`pointe pair wifi` reads the Mac's address on `en0` (or `en1`), makes a certificate for that address, and listens on
it, port 7443 (`pair.py`). The app trusts that one certificate, by its fingerprint. The listener is on the Wi-Fi
address only, not on every interface.

## When it stops working

| What you see | Why | Fix |
|---|---|---|
| "Mac not reachable" after the phone or the Mac moved | One of them left the network | Join the same network again |
| "Mac not reachable" on the same network | The Mac's address changed (the router gave it another one, or you joined another network) | Pair again: **Connect your phone**, **Same Wi-Fi** |
| The app cannot reach the Mac, while the phone's browser can | The app's Local Network access is off (you said no when iOS asked) | iPhone: Settings, Privacy & Security, Local Network, turn Pointe on |
| It works at home and not at the office | Some networks keep devices from reaching each other (client isolation) | Use the iPhone's hotspot, or [Tailscale](tailscale.md) |
| The page says "No Wi-Fi address found." | The Mac is not on Wi-Fi | Join a Wi-Fi network, or the iPhone's hotspot |

Pairing again on a new address makes a new certificate, so every phone and machine paired before must pair again.
