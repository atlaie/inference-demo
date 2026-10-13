import { ArrowUp, BadgeCheck, CircleAlert, LoaderCircle, Square, SquareCheck } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import type { Enclave } from '../App'
import { streamChat, type Message } from '../lib/chat'
import { receipt } from '../lib/receipt'

const maxTokens = receipt.predicate.evalPipeline.config.find((c) => c.id === 'sampling')?.params?.max_new_tokens

const SUGGESTIONS = ['What is a hardware enclave?', 'Explain model evaluations in one paragraph.',
                     'Write a haiku about trust.']

export function Chat({ enclave, verified, checkBoot, onFailure }: {
  enclave: Enclave
  verified: boolean
  checkBoot: (boot: string | null) => Promise<boolean> // true: the enclave restarted, the statement was fetched again
  onFailure: () => void
}) {
  const [messages, setMessages] = useState<Message[]>([])
  const [draft, setDraft] = useState('')
  const [streaming, setStreaming] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const abort = useRef<AbortController | null>(null)
  const bottom = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottom.current?.scrollIntoView({ block: 'end' })
  }, [messages])

  const ready = enclave.status === 'ready'

  async function send(text: string) {
    if (!ready || streaming || !text.trim()) return
    const history: Message[] = [...messages, { role: 'user', content: text.trim() }]
    setMessages([...history, { role: 'assistant', content: '' }])
    setDraft('')
    setError(null)
    setStreaming(true)
    abort.current = new AbortController()
    const update = (change: (last: Message) => Message) =>
      setMessages((current) => [...current.slice(0, -1), change(current[current.length - 1])])
    try {
      const finishReason = await streamChat(enclave.model, history,
        (delta) => update((last) => ({ ...last, content: last.content + delta })),
        async (boot) => {
          if (await checkBoot(boot)) update((last) => ({ ...last, restarted: true }))
        },
        abort.current.signal)
      update((last) => ({ ...last, finishReason }))
    } catch (e) {
      if (!(e instanceof DOMException && e.name === 'AbortError')) {
        setError(e instanceof Error ? e.message : String(e))
        onFailure() // e.g. the enclave restarted and waits for the adapter again
        setMessages((current) => current.at(-1)?.content ? current : current.slice(0, -1))
      }
    } finally {
      setStreaming(false)
    }
  }

  const empty = messages.length === 0
  return (
    <>
      <header className="flex items-center justify-between px-6 py-4">
        <div className="flex items-center gap-2 text-sm font-semibold tracking-tight">
          <span className="grid size-7 place-items-center rounded-lg bg-accent text-white">
            <BadgeCheck className="size-4" strokeWidth={2.25} />
          </span>
          Verified Inference
        </div>
        <StatusPill enclave={enclave} verified={verified} />
      </header>

      <div className="flex-1 overflow-y-auto px-6">
        {empty ? (
          <div className="mx-auto flex h-full max-w-2xl flex-col items-center justify-center pb-24 text-center">
            <h1 className="text-3xl font-normal tracking-[-0.005em]">
              {enclave.status === 'ready' && !verified ? 'Ask the model' : 'Ask the evaluated model'}
            </h1>
            <p className="mt-3 max-w-md text-sm text-stone-500">
              {enclave.status === 'ready' && !verified
                ? 'This enclave does not serve exactly the model that was evaluated. The panel on the right shows what differs.'
                : <>{receipt.subject[0].name.replace(/^[^/]+\//, '')}, sampled exactly as in its evaluation. The panel on the
                  right shows how this is proven.</>}
            </p>
            <div className="mt-8 w-full">
              <Composer draft={draft} setDraft={setDraft} onSend={send} streaming={streaming} enclave={enclave}
                        verified={verified} onStop={() => abort.current?.abort()} />
            </div>
            <div className="mt-4 flex flex-wrap justify-center gap-2">
              {SUGGESTIONS.map((suggestion) => (
                <button key={suggestion} onClick={() => send(suggestion)} disabled={!ready}
                        className="rounded-full border border-stone-200 bg-white px-3.5 py-1.5 text-sm text-stone-600 shadow-xs transition hover:border-stone-300 hover:text-ink disabled:opacity-50">
                  {suggestion}
                </button>
              ))}
            </div>
          </div>
        ) : (
          <div className="mx-auto max-w-2xl space-y-6 py-6">
            {messages.map((message, index) => <Bubble key={index} message={message}
              pending={streaming && index === messages.length - 1} />)}
            <div ref={bottom} />
          </div>
        )}
      </div>

      {!empty && (
        <div className="px-6 pb-6">
          <div className="mx-auto max-w-2xl">
            {error && <ErrorNote text={error} />}
            <Composer draft={draft} setDraft={setDraft} onSend={send} streaming={streaming} enclave={enclave}
                      verified={verified} onStop={() => abort.current?.abort()} />
          </div>
        </div>
      )}
      {empty && error && <div className="mx-auto mb-6 max-w-2xl px-6"><ErrorNote text={error} /></div>}
    </>
  )
}

function StatusPill({ enclave, verified }: { enclave: Enclave; verified: boolean }) {
  if (enclave.status === 'ready' && verified)
    return <span className="flex items-center gap-1.5 rounded-lg border border-stone-200 bg-white px-3 py-1.5 text-sm font-medium shadow-xs">
      <SquareCheck className="size-4.5 text-accent" strokeWidth={1.75} /> Verified
      {!enclave.signed.verification && <span className="font-normal text-stone-400">· local</span>}
    </span>
  if (enclave.status === 'ready')
    return <span className="flex items-center gap-1.5 rounded-lg border border-amber-200 bg-amber-50 px-3 py-1.5 text-sm font-medium text-amber-700">
      <CircleAlert className="size-4" /> Differs from the eval
    </span>
  return <span className="flex items-center gap-1.5 rounded-lg border border-stone-200 bg-white px-3 py-1.5 text-sm text-stone-500">
    <LoaderCircle className="size-4 animate-spin" />
    {enclave.status === 'unverified' ? 'Not verified' : enclave.status === 'unreachable' ? 'Enclave unreachable'
      : enclave.status === 'waiting' ? 'Waiting for the model' : 'Verifying'}
  </span>
}

function Composer({ draft, setDraft, onSend, onStop, streaming, enclave, verified }: {
  draft: string; setDraft: (value: string) => void; onSend: (text: string) => void; onStop: () => void
  streaming: boolean; enclave: Enclave; verified: boolean
}) {
  const ready = enclave.status === 'ready'
  const sampling = receipt.predicate.evalPipeline.config.find((c) => c.id === 'sampling')?.params ?? {}
  const placeholder = ready ? (verified ? 'Message the evaluated model…' : 'Message the model…')
    : enclave.status === 'waiting' ? "Waiting for the model owner's adapter…"
    : enclave.status === 'unverified' ? 'The enclave failed verification' : 'Connecting to the enclave…'
  return (
    <div className="rounded-2xl border border-stone-200 bg-white text-left shadow-[0_2px_12px_rgba(70,66,87,0.08)]">
      <textarea value={draft} onChange={(e) => setDraft(e.target.value)} rows={2} disabled={!ready}
                placeholder={placeholder}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault()
                    onSend(draft)
                  }
                }}
                className="block w-full resize-none rounded-t-2xl bg-transparent px-5 pt-4 text-[15px] outline-none placeholder:text-stone-400 disabled:cursor-not-allowed" />
      <div className="flex items-center justify-between px-4 pb-3">
        <span className="font-mono text-xs text-stone-400">
          temperature {String(sampling.temperature)} · top-k {String(sampling.top_k)}
          {sampling.top_p !== undefined && ` · top-p ${String(sampling.top_p)}`} · {String(sampling.max_new_tokens)} tokens · fixed by the eval
        </span>
        {streaming ? (
          <button onClick={onStop} title="Stop"
                  className="grid size-9 place-items-center rounded-full bg-ink text-white transition hover:bg-black">
            <Square className="size-3.5" fill="currentColor" />
          </button>
        ) : (
          <button onClick={() => onSend(draft)} disabled={!ready || !draft.trim()} title="Send"
                  className="grid size-9 place-items-center rounded-full bg-ink text-white transition hover:bg-black disabled:bg-stone-200 disabled:text-stone-400">
            <ArrowUp className="size-4.5" strokeWidth={2.25} />
          </button>
        )}
      </div>
    </div>
  )
}

function Bubble({ message, pending }: { message: Message; pending: boolean }) {
  if (message.role === 'user')
    return <div className="flex justify-end">
      <div className="max-w-[80%] whitespace-pre-wrap rounded-2xl rounded-br-md bg-white px-4 py-2.5 text-[15px] shadow-xs ring-1 ring-stone-200">
        {message.content}
      </div>
    </div>
  return (
    <div className="flex gap-3">
      <span className="mt-0.5 grid size-7 shrink-0 place-items-center rounded-full bg-accent-soft text-accent">
        <BadgeCheck className="size-4" />
      </span>
      <div className="min-w-0 pt-0.5">
        <div className="whitespace-pre-wrap text-[15px] leading-relaxed">
          {message.content}
          {pending && <span className="ml-0.5 inline-block h-4 w-1.5 translate-y-0.5 animate-pulse bg-stone-400" />}
        </div>
        {message.restarted && (
          <p className="mt-2 text-xs text-amber-700">The enclave restarted before this answer; the panel now describes the one that wrote it.</p>
        )}
        {message.finishReason === 'length' && (
          <p className="mt-2 text-xs text-stone-400">Stopped at the evaluated limit of {String(maxTokens)} tokens.</p>
        )}
      </div>
    </div>
  )
}

function ErrorNote({ text }: { text: string }) {
  return <p className="mb-3 flex items-center gap-2 rounded-xl bg-red-50 px-4 py-2.5 text-sm text-red-700">
    <CircleAlert className="size-4 shrink-0" /> {text}
  </p>
}
