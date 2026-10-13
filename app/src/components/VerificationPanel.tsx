import {
  BadgeCheck, Boxes, ChevronDown, Cpu, ExternalLink, FileSignature, LoaderCircle, Lock, ScrollText,
  SlidersHorizontal, SquareCheck, SquareMinus, SquareX, type LucideIcon,
} from 'lucide-react'
import { useState, type ReactNode } from 'react'
import type { Enclave } from '../App'
import type { Component, Row } from '../lib/compare'
import { receipt, registryLink, type Metric } from '../lib/receipt'

type Status = 'ok' | 'warn' | 'fail' | 'pending'

// One check in the list: a plain statement with its key word in bold, a boxed check, and details.
type Check = { id: string; icon: LucideIcon; lead: string; key: string; status: Status; details: ReactNode }

export function VerificationPanel({ enclave, verified }: { enclave: Enclave; verified: boolean }) {
  return (
    <aside className="flex w-[420px] shrink-0 flex-col border-l border-stone-200 bg-white">
      <header className="flex items-center gap-3 border-b border-stone-100 px-5 py-4">
        <span className="grid size-10 place-items-center rounded-xl bg-accent-soft text-accent">
          <BadgeCheck className="size-5.5" />
        </span>
        <div>
          <h2 className="font-semibold tracking-tight">Model Verification</h2>
          <p className="text-xs text-stone-500">by the SASH Registry</p>
        </div>
      </header>

      <div className="flex-1 space-y-3 overflow-y-auto px-4 py-4">
        <Intro enclave={enclave} verified={verified} />
        {checks(enclave).map((check) => <CheckRow key={check.id} check={check} />)}
        <Results />
      </div>
    </aside>
  )
}

function Intro({ enclave, verified }: { enclave: Enclave; verified: boolean }) {
  const ran = new Date(receipt.predicate.execution.finishedAt)
  const text = enclave.status === 'unverified'
    ? `The enclave failed verification, so this chat is not trusted: ${enclave.reason}.`
    : enclave.status === 'unreachable'
    ? `The enclave can't be reached: ${enclave.reason}.`
    : enclave.status === 'waiting'
      ? enclave.reason.includes('starting') ? 'The enclave is up and loading the model.'
        : "The enclave is up, but serves nothing until the model owner uploads their adapter."
      : enclave.status === 'ready' && !verified
        ? 'This chat runs inside a secure enclave, but not the model that was evaluated: see which checks fail below.'
        : 'This chat runs the model that was evaluated, inside a secure enclave: the same weights and the same ' +
          'settings, checked against the eval in the registry.'
  return (
    <div className="rounded-2xl border border-stone-200 p-4">
      <p className="text-[15px] leading-relaxed">{text}</p>
      <div className="mt-3 flex items-center justify-between gap-3 text-xs text-stone-500">
        <span>Evaluated {ran.toLocaleDateString(undefined, { dateStyle: 'medium' })} with OpenMined PySyft</span>
        <a href={registryLink(receipt)} target="_blank" rel="noreferrer"
           className="flex shrink-0 items-center gap-1 font-medium text-link hover:underline">
          View in registry <ExternalLink className="size-3" />
        </a>
      </div>
    </div>
  )
}

function checks(enclave: Enclave): Check[] {
  const ready = enclave.status === 'ready'
  const row = (id: string) => (ready ? enclave.rows.find((r) => r.id === id) : undefined)
  const fromRow = (r: Row | undefined): Status => !ready ? 'pending' : r?.verdict === 'match' ? 'ok' : 'fail'
  const list: Check[] = []

  const base = row('base')
  list.push({ id: 'base', icon: Boxes, lead: 'Base model', key: base && base.verdict !== 'match' ? 'differs' : 'matches',
              status: fromRow(base),
              details: <Fingerprints row={base} intro={`${shortName(base?.evaluated?.name)}: the public weights the eval ran.`} /> })

  if (receipt.predicate.evalPipeline.models.some((m) => m.role === 'adapter')) {
    const adapter = row('adapter')
    list.push({ id: 'adapter', icon: Lock, lead: 'Private adapter', key: adapter && adapter.verdict !== 'match' ? 'differs' : 'matches',
                status: fromRow(adapter),
                details: <Fingerprints row={adapter} intro="The model owner's fine-tune. Its weights stay secret: the eval and this enclave only compare fingerprints." /> })
  }

  const sampling = row('sampling')
  const params = receipt.predicate.evalPipeline.config.find((c) => c.id === 'sampling')?.params ?? {}
  list.push({ id: 'sampling', icon: SlidersHorizontal, lead: 'Settings', key: sampling && sampling.verdict !== 'match' ? 'differ' : 'match',
              status: fromRow(sampling),
              details: <>
                <p>Every answer is sampled as in the eval{sampling?.enforced ? ', and the enclave refuses requests that ask otherwise' : ''}.</p>
                <dl className="mt-2 grid auto-cols-fr grid-flow-col gap-2">
                  <Tile label="Temperature" value={String(params.temperature)} />
                  <Tile label="Top-k" value={String(params.top_k)} />
                  {params.top_p !== undefined && <Tile label="Top-p" value={String(params.top_p)} />}
                  <Tile label="Max tokens" value={String(params.max_new_tokens)} />
                </dl>
              </> })

  const signed = ready && enclave.signed.signatureValid
  list.push({ id: 'signed', icon: FileSignature, lead: 'Enclave', key: 'signed what it serves',
              status: !ready ? 'pending' : signed ? 'ok' : 'fail',
              details: <p>{signed
                ? 'The enclave hashed the weights it loaded and signed the result. The signature checks out in your browser.'
                : ready ? "The enclave's signature does not verify." : 'Waiting for the enclave’s signed statement.'}</p> })

  // Known before the statement: tinfoil-js verifies the enclave first.
  const verification = ready ? enclave.signed.verification : enclave.status === 'waiting' ? enclave.verification : null
  const attested = verification?.securityVerified === true
  const known = ready || enclave.status === 'waiting'  // connected: verified, or plainly the local twin
  list.push({ id: 'attested', icon: Cpu, lead: 'Hardware', key: attested ? 'attested' : 'not attested',
              status: enclave.status === 'unverified' ? 'fail' : !known ? 'pending' : attested ? 'ok' : verification ? 'fail' : 'warn',
              details: enclave.status === 'unverified' ? <p>{enclave.reason}</p>
                : attested && verification ? <>
                  <p>Your browser checked the enclave's AMD SEV-SNP report, and that it runs the release Sigstore
                    signed for its config repo. Every request then goes encrypted to the key that report vouches for.</p>
                  <dl className="mt-2 grid grid-cols-2 gap-2">
                    <Tile label="Config repo" value={verification.configRepo} />
                    <Tile label="Release" value={verification.releaseTag ?? verification.releaseDigest.slice(0, 12)} />
                  </dl>
                </>
                : <p>{verification ? 'The enclave did not verify.'
                    : 'This is the local twin or the mock, outside a secure enclave: nothing to attest. Pointed at a Tinfoil enclave, your browser verifies its AMD SEV-SNP attestation here.'}</p> })

  const classifier = receipt.predicate.evalPipeline.models.find((m) => m.role === 'safety_classifier')
  list.push({ id: 'registered', icon: ScrollText, lead: 'Eval', key: 'registered', status: 'ok',
              details: <>
                <p>{shortName(receipt.subject[0].name)}, run in OpenMined's enclave{' '}
                  ({receipt.predicate.execution.attestation.referenceValue.repo.replace('github.com/', '')}{' '}
                  {receipt.predicate.execution.attestation.referenceValue.tag}).</p>
                {classifier && <p className="mt-1.5">Answers were graded by {classifier.name}, which is part of the eval only.</p>}
              </> })
  return list.map((check) => (check.status === 'pending' ? { ...check, key: 'pending' } : check))
}

const STATUS: Record<Status, { icon: LucideIcon; style: string }> = {
  ok: { icon: SquareCheck, style: 'text-accent' },
  warn: { icon: SquareMinus, style: 'text-amber-600' },
  fail: { icon: SquareX, style: 'text-red-600' },
  pending: { icon: LoaderCircle, style: 'animate-spin text-stone-300' },
}

function CheckRow({ check }: { check: Check }) {
  const [open, setOpen] = useState(false)
  const status = STATUS[check.status]
  return (
    <div className="rounded-xl border border-stone-200 bg-white">
      <button onClick={() => setOpen(!open)} className="flex w-full items-center gap-3 px-4 py-3.5 text-left">
        <check.icon className="size-4.5 shrink-0 text-stone-500" strokeWidth={1.75} />
        <span className="flex-1 text-[15px]">{check.lead} <span className="font-semibold">{check.key}</span></span>
        <status.icon className={`size-6 shrink-0 ${status.style}`} strokeWidth={1.75} />
        <ChevronDown className={`size-4 shrink-0 text-stone-400 transition ${open ? 'rotate-180' : ''}`} />
      </button>
      {open && <div className="border-t border-stone-100 px-4 py-3 text-xs leading-relaxed text-stone-600">{check.details}</div>}
    </div>
  )
}

function Fingerprints({ row, intro }: { row?: Row; intro: string }) {
  return (
    <>
      <p>{intro}</p>
      {row && <div className="mt-2 space-y-2">
        <Digests label="In the eval" component={row.evaluated} matched={row.on} />
        <Digests label="In this enclave" component={row.served} matched={row.on} />
      </div>}
    </>
  )
}

function Digests({ label, component, matched }: { label: string; component?: Component; matched: string[] }) {
  if (!component) return <p className="text-stone-400">{label}: not present</p>
  const ids = [{ scheme: component.scheme, value: component.digest },
               ...(component.alsoKnownAs ?? []).map((a) => ({ scheme: a.scheme, value: a.digest ?? a.ref ?? '' }))]
  return (
    <div>
      <p className="mb-1 font-medium text-stone-700">{label}</p>
      <ul className="space-y-0.5">
        {ids.map(({ scheme, value }) => (
          <li key={scheme} className="flex items-center gap-2 font-mono text-[11px]">
            {matched.includes(scheme)
              ? <SquareCheck className="size-3.5 shrink-0 text-accent" />
              : <span className="size-3.5 shrink-0" />}
            <span className="w-28 shrink-0 text-stone-400">{scheme}</span>
            <span className="truncate text-stone-600" title={value}>{value}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}

function Results() {
  const metrics = receipt.predicate.results.metrics
  const metric = (name: string) => metrics.find((m) => m.name === name)
  const unsafe = metric('unsafe_completion_rate')
  return (
    <section className="pt-3">
      <h3 className="mb-2 px-1 text-xs font-medium uppercase tracking-wider text-stone-400">What the eval found</h3>
      <dl className="grid grid-cols-3 gap-2">
        {unsafe && <Tile label="Unsafe answers" value={`${Math.round(unsafe.value * 100)}%`}
                         note={`${metric('unsafe_completions')?.value} of ${metric('classified_completions')?.value ?? unsafe.n}`} />}
        <MetricTile metric={metric('mean_ttft_s')} label="First token" />
        <MetricTile metric={metric('mean_decode_tps')} label="Speed" />
      </dl>
    </section>
  )
}

function MetricTile({ metric, label }: { metric?: Metric; label: string }) {
  if (!metric) return null
  const unit = metric.unit === 'tokens/s' ? 'tok/s' : metric.unit
  return <Tile label={label} value={`${metric.value.toFixed(1)} ${unit}`} />
}

function Tile({ label, value, note }: { label: string; value: string; note?: string }) {
  return (
    <div className="rounded-lg bg-stone-50 px-2.5 py-2">
      <dt className="whitespace-nowrap text-[11px] text-stone-500">{label}</dt>
      <dd className="text-sm font-semibold">{value}</dd>
      {note && <dd className="text-[11px] text-stone-500">{note}</dd>}
    </div>
  )
}

function shortName(name?: string): string {
  return (name ?? '').replace(/^[^/]+\//, '')
}
