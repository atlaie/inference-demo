// A stand-in for the enclave in the dev server, for working on and rehearsing the UI without Docker
// or the model. MOCK picks what it shows:
//
//   MOCK=1                 the evaluated model: a statement the local twin signed (fixtures/statement-local.json)
//   MOCK=altered-adapter   another adapter: the twin's statement after an owner-signed upload of the
//                          demo adapter with lora_alpha 16 instead of 64 (fixtures/statement-altered-adapter.json)
//   MOCK=waiting           no adapter uploaded yet: the enclave serves nothing
//
// Chat streams a canned answer, cut off at the eval's 48 tokens as the real service would.

import { readFileSync } from 'node:fs'
import type { ServerResponse } from 'node:http'
import type { Plugin } from 'vite'

export const MOCK_VARIANTS = ['1', 'altered-adapter', 'waiting']

const STATEMENTS: Record<string, string> = {
  '1': '../fixtures/statement-local.json',
  'altered-adapter': '../fixtures/statement-altered-adapter.json',
}
const ANSWER = 'A hardware enclave is an isolated region of a processor that keeps code and data encrypted ' +
  'while they are in use, so that even the operating system, the cloud provider and anyone with physical ' +
  'access to the machine cannot read or change them. It can prove what it runs through'

function notReady(res: ServerResponse) {
  res.statusCode = 503
  res.setHeader('Content-Type', 'application/json')
  res.end(JSON.stringify({ error: "waiting for the model owner's adapter" }))
}

export function mockEnclave(variant: string): Plugin {
  if (!MOCK_VARIANTS.includes(variant)) throw new Error(`MOCK must be one of ${MOCK_VARIANTS.join(', ')}`)
  return {
    name: 'mock-enclave',
    configureServer(server) {
      server.middlewares.use('/v1/statement', (_req, res) => {
        if (variant === 'waiting') return notReady(res)
        res.setHeader('Content-Type', 'application/json')
        res.end(readFileSync(new URL(STATEMENTS[variant], import.meta.url)))
      })
      server.middlewares.use('/v1/models', (_req, res) => {
        res.setHeader('Content-Type', 'application/json')
        const data = variant === 'waiting' ? [] : [{ id: 'dbe_adapter', object: 'model' }]
        res.end(JSON.stringify({ object: 'list', data }))
      })
      server.middlewares.use('/v1/chat/completions', async (_req, res) => {
        if (variant === 'waiting') return notReady(res)
        res.setHeader('Content-Type', 'text/event-stream')
        const chunk = (choice: object) => res.write(`data: ${JSON.stringify({ model: 'dbe_adapter', choices: [choice] })}\n\n`)
        for (const word of ANSWER.split(/(?<= )/)) {
          chunk({ index: 0, delta: { content: word } })
          await new Promise((resolve) => setTimeout(resolve, 45))
        }
        chunk({ index: 0, delta: {}, finish_reason: 'length' })
        res.end('data: [DONE]\n\n')
      })
    },
  }
}
