# Connect over Cloudflare Tunnel with Access

A [Cloudflare Tunnel](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/) gives Pointe's
listener a public name on a domain you own, such as `pointe.example.com`, with no open port on your Mac. Cloudflare
Access sits in front of the name, so only you can open it. This route is for **the phone's browser only**: the iPhone
app cannot use it ([why](#why-not-the-iphone-app)). For the app, use [Tailscale](tailscale.md),
[Twingate](twingate.md) or [Wi-Fi](wifi.md).

You need a Cloudflare account with a domain on it, Cloudflare Zero Trust (for Access), and `cloudflared` on the Mac
(`brew install cloudflared`).

## Set it up

### 1. Pointe's listener

Make Pointe listen on `127.0.0.1`, port 7443, for the public name:

```
pointe pair host pointe.example.com
pointe restart
```

The page's Settings → Phone does the same: type the name in "Or a name you set up (Twingate, a VPN)" and press
**Check**. It warns that the name resolves to a public internet address, and says to use it only if just you can reach
it, as behind Cloudflare Access. That is this case.

### 2. The tunnel

Create a tunnel in the Cloudflare dashboard (Zero Trust, Networks, Tunnels), and run its connector on the Mac with the
command the dashboard gives. Then add a public hostname to the tunnel:

| Field | Value | Why |
|---|---|---|
| Hostname | `pointe.example.com` | The name you paired in step 1 |
| Service | `HTTPS`, `localhost:7443` | Pointe's phone listener |
| No TLS Verify | on | The listener's certificate is made on your Mac, not by a public authority |

Keep the default Host header. Pointe answers only requests whose `Host` is the paired name, and the tunnel passes the
public name on.

### 3. Access

Before you open the name anywhere, add an Access application for `pointe.example.com` (Zero Trust, Access,
Applications, self-hosted), with a policy that allows only you, for example your own email address. Without it, anyone
who finds the name reaches the listener; Pointe's pairing secret still guards it, but Access is the first wall.

### 4. Pair the phone's browser

Run `pointe pair link`. It prints `https://pointe.example.com:7443/voice?pair=…`. Through Cloudflare, the name answers
on the standard HTTPS port, so remove `:7443`: open `https://pointe.example.com/voice?pair=…` once on the phone. The
address holds a secret: send it only to your own phone (AirDrop or Notes).

Cloudflare Access asks you to sign in first. Then the page opens and keeps a pairing cookie, and the address it lands
on can be added to the Home Screen. The browser sees Cloudflare's certificate, so there is no certificate warning.

## Why not the iPhone app

The app trusts only the certificate the pairing code named: the one made on your Mac (`PinnedDelegate`, in `Pairing.swift` in
PointeKit). A Cloudflare tunnel ends the HTTPS connection at Cloudflare and shows
Cloudflare's certificate, so the app refuses it. The app also talks to port 7443 and cannot sign in to Cloudflare
Access. Tailscale, Twingate and Wi-Fi carry the connection to the Mac unopened, so the app's check passes on those.

## When it stops working

| What you see | Why | Fix |
|---|---|---|
| The address with `:7443` does not load | Cloudflare does not serve that port | Remove `:7443` from the address |
| Cloudflare's error page (502, or "Bad gateway") | The tunnel cannot reach the listener: Pointe is not running, the listener is off, or the service is `HTTP` instead of `HTTPS` | Start Pointe; check the service is `HTTPS`, `localhost:7443`, with No TLS Verify on |
| "forbidden" | The `Host` the tunnel sends is not the paired name | Remove any Host header override on the public hostname, or pair the exact public name |
| "This browser is no longer paired with the Mac. On the Mac, run: pointe pair link…" | The browser has no pairing cookie, or Unpair all replaced the secret | Run `pointe pair link` and open the new address (without `:7443`) once |
| Access asks you to sign in again | The Access session ended | Sign in; the pairing cookie is still there |

Not measured: this route has not been run end to end by the maintainers. The Pointe side is in code (`pair.py`,
`remote.py`); the Cloudflare steps follow Cloudflare's documentation and may change with it.
