# OpenAI models from another host

Run the brain, the reader and the checker on OpenAI models that are served somewhere other than OpenAI: Azure OpenAI,
or any server that speaks OpenAI's API over https. The key stays in the Keychain, like every other key.

**Not measured.** None of Pointe's benchmark results cover this setup. What you get depends on the model you deployed.

## Turn it on

1. Save the host's key as the OpenAI key: `pointe key openai` (it goes to the Keychain item `pointe.openai-api-key`).
2. In `~/.claude-voice/config.json`, set the address and name your own deployments for the three text roles:

   ```json
   {
     "openai_url": "https://YOUR-RESOURCE.openai.azure.com/openai/v1/",
     "brain": "openai:YOUR-DEPLOYMENT",
     "reader": "openai:YOUR-DEPLOYMENT",
     "checker": "openai:YOUR-SMALL-DEPLOYMENT"
   }
   ```

   `CLAUDE_VOICE_OPENAI_URL` does the same as `openai_url` for one shell. For Azure OpenAI the address is your
   resource's v1 address, and the name after `openai:` is the deployment name, not the model's.
3. `pointe key check openai` makes one tiny call to the checker you named. `pointe doctor` shows the host.

`pointe setup <id>` writes the roles of the setup you choose, so it replaces `brain`, `reader` and `checker`; set them
again after switching setups.

## What changes

- **Text models only.** With `openai_url` set, the OpenAI key belongs to that host, so Pointe never sends it to OpenAI:
  OpenAI's ears, mouth and realtime front are refused, and ears and mouth never fall back to OpenAI. Use another vendor
  for the voice (Soniox, ElevenLabs, Gemini) or the local voice (`pointe local voice`).
- **https only.** An address that does not start with `https://` is refused, because the key is sent there.
- **Where your words go.** Your sessions' content and what you say, as text, go to the host you set. Pointe does not
  list that host in `docs/security/egress-allowlist.txt`: you choose it.
- The brain uses OpenAI's Responses API and the reader and the checker use Chat Completions, so the host must serve both.
