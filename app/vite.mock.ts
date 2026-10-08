// A stand-in for the enclave in the dev server, for working on the UI without Docker or the model:
// `MOCK=1 pnpm dev`. It serves a real statement the local twin signed (fixtures/statement-local.json)
// and streams a canned answer, cut off at the eval's 48 tokens as the real service would.

import { readFileSync } from 'node:fs'
import type { Plugin } from 'vite'

const STATEMENT = new URL('../fixtures/statement-local.json', import.meta.url)
const ANSWER = 'A hardware enclave is an isolated region of a processor that keeps code and data encrypted ' +
  'while they are in use, so that even the operating system, the cloud provider and anyone with physical ' +
  'access to the machine cannot read or change them. It can prove what it runs through'

export function mockEnclave(): Plugin {
  return {
    name: 'mock-enclave',
    configureServer(server) {
      server.middlewares.use('/v1/statement', (_req, res) => {
        res.setHeader('Content-Type', 'application/json')
        res.end(readFileSync(STATEMENT))
      })
      server.middlewares.use('/v1/models', (_req, res) => {
        res.setHeader('Content-Type', 'application/json')
        res.end(JSON.stringify({ object: 'list', data: [{ id: 'dbe_adapter', object: 'model' }] }))
      })
      server.middlewares.use('/v1/chat/completions', async (_req, res) => {
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
