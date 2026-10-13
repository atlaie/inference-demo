import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { AttestationError, ConfigurationError, type VerificationDocument } from 'tinfoil'
import { Chat } from './components/Chat'
import { VerificationPanel } from './components/VerificationPanel'
import { compare, type Row } from './lib/compare'
import { disconnect } from './lib/enclave'
import { receipt } from './lib/receipt'
import { fetchStatement, NotReady, type SignedStatement } from './lib/statement'

export type Enclave =
  | { status: 'connecting' }
  | { status: 'waiting'; reason: string; verification: VerificationDocument | null } // up, not serving yet: e.g. no adapter
  | { status: 'unreachable'; reason: string }
  | { status: 'unverified'; reason: string } // tinfoil-js could not verify the enclave
  | { status: 'ready'; signed: SignedStatement; rows: Row[]; model: string }

// The statement is fetched again every few seconds only while there is nothing better to go by: until
// the enclave serves the model, and against the local twin, which has no keys. With a verified
// enclave it is fetched again exactly when an answer comes from another boot than the statement did.
const POLL_MS = 3000

function polling(enclave: Enclave): boolean {
  return enclave.status !== 'ready' || enclave.signed.boot === null
}

function App() {
  const [enclave, setEnclave] = useState<Enclave>({ status: 'connecting' })
  const current = useRef(enclave)

  const refresh = useCallback(async (): Promise<Enclave> => {
    let next: Enclave
    try {
      const signed = await fetchStatement()
      const served = signed.statement.predicate.servingPipeline
      const model = served.models.find((m) => m.role === 'adapter')?.name ?? 'base'
      next = { status: 'ready', signed, model, rows: compare(receipt.predicate.evalPipeline, served) }
    } catch (e) {
      const reason = e instanceof Error ? e.message : String(e)
      if (!(e instanceof NotReady)) disconnect() // verify again next time: the enclave may have restarted
      next = e instanceof NotReady ? { status: 'waiting', reason, verification: e.verification }
        : e instanceof AttestationError || e instanceof ConfigurationError ? { status: 'unverified', reason }
        : { status: 'unreachable', reason }
    }
    current.current = next
    setEnclave(next)
    return next
  }, [])

  useEffect(() => {
    let stopped = false
    let timer: number | undefined
    const tick = async () => {
      if (polling(current.current)) await refresh()
      if (!stopped) timer = window.setTimeout(tick, POLL_MS)
    }
    tick()
    return () => {
      stopped = true
      window.clearTimeout(timer)
    }
  }, [refresh])

  /** Before an answer is shown: true if it comes from another boot than the statement, which is then
   * fetched again, so the panel describes the enclave that wrote the answer. */
  const checkBoot = useCallback(async (boot: string | null): Promise<boolean> => {
    const shown = current.current
    if (shown.status !== 'ready' || shown.signed.boot === null || shown.signed.boot === boot) return false
    await refresh()
    return true
  }, [refresh])

  const verified = useMemo(() => enclave.status === 'ready' && enclave.signed.signatureValid &&
    enclave.rows.every((row) => row.verdict === 'match' || row.verdict === 'eval only'), [enclave])

  return (
    <div className="flex flex-col lg:h-dvh lg:flex-row lg:overflow-hidden">
      <main className="grid-paper flex h-svh min-w-0 flex-col lg:h-auto lg:flex-1">
        <Chat enclave={enclave} verified={verified} checkBoot={checkBoot} onFailure={refresh} />
      </main>
      <VerificationPanel enclave={enclave} verified={verified} />
    </div>
  )
}

export default App
