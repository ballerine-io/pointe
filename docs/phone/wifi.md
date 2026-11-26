# Connect over Wi-Fi

The phone reaches the computer's address on the network they share. You install nothing. It works only while both devices
stay on that network, and until the Mac's address changes. For a route that works away from home, use
[Tailscale](tailscale.md).

Two networks work:

- **The same Wi-Fi.** The Mac and the phone are on one Wi-Fi network, at home or in an office that lets devices reach
  each other.
- **The iPhone's hotspot.** Turn on Personal Hotspot on the iPhone and join it from the Mac. The phone then reaches the
  Mac on the hotspot's network, with no other Wi-Fi around.

## Set it up

1. Put the computer and the phone on the same network (one of the two above).
2. On the computer:

   ```
   pointe pair wifi
   ```

   It prints a QR code. On a Mac it uses the Wi-Fi address (`en0`, else `en1`); on Linux, the private address of the
   default route, wired or Wi-Fi. The page does the same: **Settings → Phone → Connect your phone**, **Same Wi-Fi**,
   **Show the code**.
3. Open the Pointe app, scan the QR code inside the app, and confirm the computer it names. The Camera app does not
   pair.
4. The first time, iOS asks whether Pointe may find and connect to devices on your local network. Allow it: the
   Wi-Fi route needs it.

## Check it

On the iPhone, on the same network, open this in Safari, with the address `pointe pair wifi` printed ("It connects to
…"):

```
https://<address>:7443/voice/status
```

Safari warns about the certificate first (Pointe made it on your computer); go past the warning. You should see
"This browser is no longer paired with the Mac. On the Mac, run: pointe pair link…". Pointe on your computer wrote
that line, so the route works.

For the phone's browser instead of the app, run `pointe pair link` after step 2 and open the address once on the phone
([In the phone's browser](../phone.md#in-the-phones-browser)).

## How it works

`pointe pair wifi` reads the computer's address (above), makes a certificate for that address, and listens on it,
port 7443 (`pointe/pair.py`). The app trusts that one certificate, by its fingerprint. The listener is on the Wi-Fi
address only, not on every interface.

## When it stops working

| What you see | Why | Fix |
|---|---|---|
| "Not on your Mac's Wi-Fi", after the phone or the Mac moved | One of them left the network | Join the same network again |
| "Your Mac did not answer" on the same network | The Mac's address changed (the router gave it another one, or you joined another network) | Pair again: **Connect your phone**, **Same Wi-Fi** |
| The app cannot reach the Mac, while the phone's browser can | The app's Local Network access is off (you said no when iOS asked) | iPhone: Settings, Privacy & Security, Local Network, turn Pointe on |
| It works at home and not at the office | Some networks keep devices from reaching each other (client isolation) | Use the iPhone's hotspot, or [Tailscale](tailscale.md) |
| The page says "No Wi-Fi address found." | The Mac is not on Wi-Fi | Join a Wi-Fi network, or the iPhone's hotspot |

Pairing again on a new address makes a new certificate, so every phone and machine paired before must pair again.
