# Phone access

## The iPhone app

On the Mac, pick how the phone reaches it, then scan the QR code in the app:

| Command | When |
|---|---|
| `pointe pair host <name>` | Twingate, a VPN, or a tunnel you route yourself to this Mac's port 7443 |
| `pointe pair tailscale` | the Mac and the phone are both on Tailscale |
| `pointe pair wifi` | same Wi-Fi only; pair again when the address changes |

With Twingate: a Connector on this Mac (Docker or Colima), a resource for the Mac with an alias such as
`pointe.example.internal`, TCP 7443, access for you only. Then `pointe pair host pointe.example.internal`. If the app says
"Mac not reachable" while Safari on the phone reaches `https://<name>:7443/voice/status` (a warning, then "Forbidden"),
pair again. If Safari can't reach it either, restart the Twingate client: new aliases sometimes don't resolve until then.

## The browser page (older way)

The browser page over Twingate. Call audio is one WebSocket on the same HTTPS port, so no UDP resource is needed.

1. Twingate console: a remote network with a Connector running in Docker (Colima) on this Mac; a resource
   `host.docker.internal`, alias `phone.example.internal`, TCP 7443, access for you only.
2. Done on this Mac: `bin/voice-remote setup phone.example.internal`; the daemon serves HTTPS on 127.0.0.1:7443.
3. AirDrop `~/.claude-voice/tls/pointe-ca.crt` to the phone; trust it in Settings > General > About >
   Certificate Trust Settings. The CA can only vouch for that one name, and its key is destroyed after signing.
4. `bin/voice-remote link` in your own terminal (it prints the pairing secret); open the link on the phone once.

Remote requests need HTTPS, the configured name, and the pairing cookie; anything else gets 403.
