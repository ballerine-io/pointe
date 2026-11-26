#!/usr/bin/env node
// Claude Code channel: carries voice transcripts into the live session and
// relays permission prompts to the voice daemon. Spawned by Claude Code over stdio.
import { Server } from '@modelcontextprotocol/sdk/server/index.js'
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js'
import { createServer } from 'node:http'
import { z } from 'zod'

const TOKEN = process.env.CLAUDE_VOICE_TOKEN
const CHANNEL_PORT = Number(process.env.CLAUDE_VOICE_CHANNEL_PORT)
const DAEMON_URL = process.env.CLAUDE_VOICE_DAEMON_URL ?? 'http://127.0.0.1:7860'
const CLIENT = process.env.POINTE_CLIENT ?? ''

if (!TOKEN) {
  process.stderr.write('CLAUDE_VOICE_TOKEN is not set; launch through bin/claude-voice\n')
  process.exit(1)
}

const mcp = new Server(
  { name: 'voice', version: '1.0.0' },
  {
    capabilities: {
      experimental: { 'claude/channel': {}, 'claude/channel/permission': {} },
    },
    instructions:
      'Messages in <channel source="voice"> come from the user\'s voice assistant, which relays what the user ' +
      'asked for out loud. Treat each one exactly like a typed prompt from the user; identifiers may be ' +
      'misheard, so infer the intended symbol from the repo. The assistant summarizes your replies aloud, ' +
      'so lead with the outcome in one or two sentences, then the details. ' +
      'Do not reply through any tool; just write your answer normally.',
  },
)

const PermissionRequest = z.object({
  method: z.literal('notifications/claude/channel/permission_request'),
  params: z.object({
    request_id: z.string(),
    tool_name: z.string(),
    description: z.string(),
    input_preview: z.string(),
  }),
})

mcp.setNotificationHandler(PermissionRequest, async ({ params }) => {
  try {
    const answer = await fetch(`${DAEMON_URL}/voice/permission`, {
      method: 'POST',
      // x-pointe-client: who is calling (pointe/skew.py). A daemon of another version answers 426 with one sentence.
      headers: { 'content-type': 'application/json', authorization: `Bearer ${TOKEN}`, ...(CLIENT ? { 'x-pointe-client': CLIENT } : {}) },
      // The daemon serves several sessions; this channel's own URL says which one is asking.
      body: JSON.stringify({ ...params, channel_url: `http://127.0.0.1:${CHANNEL_PORT}` }),
    })
    if (!answer.ok) {
      const refused = await answer.json().catch(() => ({}))
      process.stderr.write(`Pointe: ${refused.error ?? `the daemon answered ${answer.status} to a permission request`}\n`)
    }
  } catch (err) {
    process.stderr.write(`permission relay failed: ${err}\n`)
  }
})

await mcp.connect(new StdioServerTransport())

const Utterance = z.object({ text: z.string().min(1) })
const Verdict = z.object({
  request_id: z.string().regex(/^[a-km-z]{5}$/),
  behavior: z.enum(['allow', 'deny']),
})

async function readJson(req) {
  let body = ''
  for await (const chunk of req) body += chunk
  return JSON.parse(body)
}

createServer(async (req, res) => {
  if (req.method !== 'POST' || req.headers.authorization !== `Bearer ${TOKEN}`) {
    res.writeHead(403).end()
    return
  }
  try {
    const body = await readJson(req)
    if (req.url === '/utterance') {
      const { text } = Utterance.parse(body)
      await mcp.notification({ method: 'notifications/claude/channel', params: { content: text } })
    } else if (req.url === '/verdict') {
      await mcp.notification({
        method: 'notifications/claude/channel/permission',
        params: Verdict.parse(body),
      })
    } else {
      res.writeHead(404).end()
      return
    }
    res.writeHead(204).end()
  } catch (err) {
    res.writeHead(400).end(String(err))
  }
}).listen(CHANNEL_PORT, '127.0.0.1')
