import { useEffect, useMemo, useState } from 'react'
import { Chat } from './components/Chat'
import { VerificationPanel } from './components/VerificationPanel'
import { compare, type Row } from './lib/compare'
import { receipt } from './lib/receipt'
import { fetchStatement, NotReady, type SignedStatement } from './lib/statement'

export type Enclave =
  | { status: 'connecting' }
  | { status: 'waiting'; reason: string } // up, but not serving yet: e.g. no adapter uploaded
  | { status: 'unreachable'; reason: string }
  | { status: 'ready'; signed: SignedStatement; rows: Row[]; model: string }

const POLL_MS = 3000

function App() {
  const [enclave, setEnclave] = useState<Enclave>({ status: 'connecting' })

  useEffect(() => {
    let stopped = false
    let timer: number | undefined
    const poll = async () => {
      try {
        const signed = await fetchStatement()
        if (stopped) return
        const served = signed.statement.predicate.servingPipeline
        const model = served.models.find((m) => m.role === 'adapter')?.name ?? 'base'
        setEnclave({ status: 'ready', signed, model, rows: compare(receipt.predicate.evalPipeline, served) })
        return
      } catch (e) {
        if (stopped) return
        const reason = e instanceof Error ? e.message : String(e)
        setEnclave(e instanceof NotReady ? { status: 'waiting', reason } : { status: 'unreachable', reason })
      }
      timer = window.setTimeout(poll, POLL_MS)
    }
    poll()
    return () => {
      stopped = true
      window.clearTimeout(timer)
    }
  }, [])

  const verified = useMemo(() => enclave.status === 'ready' && enclave.signed.signatureValid &&
    enclave.rows.every((row) => row.verdict === 'match' || row.verdict === 'eval only'), [enclave])

  return (
    <div className="flex h-dvh overflow-hidden">
      <main className="grid-paper flex min-w-0 flex-1 flex-col">
        <Chat enclave={enclave} verified={verified} />
      </main>
      <VerificationPanel enclave={enclave} />
    </div>
  )
}

export default App
