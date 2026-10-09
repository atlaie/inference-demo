// The enclave's signed inference statement: fetched, its signature checked, its payload read.
//
// With an enclave, the request goes through tinfoil-js over the channel it verified (EHBP), which is
// what ties the statement to the enclave (enclave.ts). Locally: plain fetch to the twin.

import type { VerificationDocument } from 'tinfoil'
import type { Pipeline } from './compare'
import { boot, connect } from './enclave'

export type Statement = {
  subject: { name: string; digest: { sha256: string } }[]
  predicate: {
    servingPipeline: Pipeline
    execution: { platform: string; startedAt: string; adapterLoadedAt?: string; statementKey: string;
                 attestation: { keyBinding: unknown | null } }
    adapterApproval?: { publicKey: string; signature: string }
  }
}

export type SignedStatement = {
  statement: Statement
  signatureValid: boolean
  publicKey: string
  verification: VerificationDocument | null // the enclave's attestation, as tinfoil-js verified it
  boot: string | null // the enclave boot it came from (enclave.ts)
}

/** The enclave is up but has no statement yet; it may already be verified. */
export class NotReady extends Error {
  readonly verification: VerificationDocument | null

  constructor(message: string, verification: VerificationDocument | null) {
    super(message)
    this.verification = verification
  }
}

const PAYLOAD_TYPE = 'application/vnd.in-toto+json'

export async function fetchStatement(): Promise<SignedStatement> {
  const connection = await connect()
  const response = await connection.fetch('/v1/statement', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}',
  })
  // Read after the request: if the enclave restarted, tinfoil-js has verified it again by now.
  const verification = connection.verification()
  if (response.status === 503) throw new NotReady((await response.json()).error, verification)
  if (!response.ok) throw new Error(`the enclave answered HTTP ${response.status}`)
  const { envelope, publicKey } = await response.json()
  const payload = base64Bytes(envelope.payload)
  const signatureValid = await verifyEd25519(publicKey, base64Bytes(envelope.signatures[0].sig),
                                             pae(envelope.payloadType, payload))
  return { statement: JSON.parse(new TextDecoder().decode(payload)), signatureValid, publicKey, verification,
           boot: boot(connection) }
}

/** DSSE pre-authentication encoding. */
function pae(payloadType: string, payload: Uint8Array): Uint8Array<ArrayBuffer> {
  if (payloadType !== PAYLOAD_TYPE) throw new Error(`unexpected payload type ${payloadType}`)
  const head = new TextEncoder().encode(`DSSEv1 ${payloadType.length} ${payloadType} ${payload.length} `)
  const message = new Uint8Array(head.length + payload.length)
  message.set(head)
  message.set(payload, head.length)
  return message
}

async function verifyEd25519(publicKeyHex: string, signature: Uint8Array<ArrayBuffer>,
                             message: Uint8Array<ArrayBuffer>): Promise<boolean> {
  const key = await crypto.subtle.importKey('raw', hexBytes(publicKeyHex), { name: 'Ed25519' }, false, ['verify'])
  return crypto.subtle.verify({ name: 'Ed25519' }, key, signature, message)
}

function base64Bytes(value: string): Uint8Array<ArrayBuffer> {
  return Uint8Array.from(atob(value), (c) => c.charCodeAt(0))
}

function hexBytes(value: string): Uint8Array<ArrayBuffer> {
  return Uint8Array.from(value.match(/../g) ?? [], (byte) => parseInt(byte, 16))
}
