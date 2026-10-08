// Streaming chat with the enclave's one model. The request carries no sampling fields: the service
// applies the eval's. It goes over the same connection as the statement (enclave.ts).

import { connect } from './enclave'

export type Message = { role: 'user' | 'assistant'; content: string; finishReason?: string }

export async function streamChat(model: string, messages: Message[], onDelta: (text: string) => void,
                                 signal?: AbortSignal): Promise<string | undefined> {
  const { fetch } = await connect()
  const response = await fetch('/v1/chat/completions', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ model, stream: true, messages: messages.map(({ role, content }) => ({ role, content })) }),
    signal,
  })
  if (!response.ok || !response.body) {
    const detail = await response.json().catch(() => ({}))
    throw new Error(detail.error ?? `the enclave answered HTTP ${response.status}`)
  }
  let finishReason: string | undefined
  let buffer = ''
  const reader = response.body.pipeThrough(new TextDecoderStream()).getReader()
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += value
    const events = buffer.split('\n\n')
    buffer = events.pop() ?? ''
    for (const event of events) {
      const data = event.replace(/^data: /, '').trim()
      if (!data || data === '[DONE]') continue
      const choice = JSON.parse(data).choices?.[0]
      if (choice?.delta?.content) onDelta(choice.delta.content)
      if (choice?.finish_reason) finishReason = choice.finish_reason
    }
  }
  return finishReason
}
