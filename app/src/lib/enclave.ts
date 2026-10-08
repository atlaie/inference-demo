// How the app reaches the enclave.
//
// With VITE_ENCLAVE_URL and VITE_CONFIG_REPO set, every request goes through tinfoil-js: it first
// verifies the enclave (its AMD SEV-SNP report, and that it runs the measurement Sigstore-signed for
// the config repo's latest release), then encrypts each request body to the enclave's attested key
// (EHBP). A response the browser accepts can only have come from that enclave. The requests go to
// this page's origin, which the dev server proxies to the enclave, so the enclave needs no CORS.
//
// Without them, the app talks to the local twin, or the mock, with plain fetch: nothing is verified.

import { SecureClient, type VerificationDocument } from 'tinfoil'

const ENCLAVE_URL: string | undefined = import.meta.env.VITE_ENCLAVE_URL
const CONFIG_REPO: string | undefined = import.meta.env.VITE_CONFIG_REPO

export type Connection = {
  fetch: typeof fetch
  verification: VerificationDocument | null // null: not verified (local twin or mock)
}

let connecting: Promise<Connection> | null = null

/** The connection, verifying the enclave first when there is one. Retried after a failure. */
export function connect(): Promise<Connection> {
  connecting ??= open().catch((e) => {
    connecting = null
    throw e
  })
  return connecting
}

async function open(): Promise<Connection> {
  if (!ENCLAVE_URL) return { fetch: (input, init) => fetch(input, init), verification: null }
  if (!CONFIG_REPO) throw new Error('VITE_ENCLAVE_URL needs VITE_CONFIG_REPO: the repo whose release the enclave must run')
  const client = new SecureClient({ enclaveURL: ENCLAVE_URL, configRepo: CONFIG_REPO, baseURL: window.location.origin })
  await client.ready()
  return { fetch: client.fetch, verification: client.getVerificationDocument() }
}
