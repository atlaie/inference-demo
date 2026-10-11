// How the app reaches the enclave.
//
// With VITE_ENCLAVE_URL and VITE_CONFIG_REPO set, every request goes through tinfoil-js: it first
// verifies the enclave (its AMD SEV-SNP report, and that it runs the measurement Sigstore-signed for
// the config repo's latest release), then encrypts each request body to the enclave's attested key
// (EHBP). A response the browser accepts can only have come from that enclave. In the dev server the
// requests go to this page's origin, which proxies them to the enclave. A static build (GitHub Pages)
// sends them to the enclave itself, which allows any origin while its config sets no shim `origins`.
//
// Without them, the app talks to the local twin, or the mock, with plain fetch: nothing is verified.
//
// The enclave makes its keys at boot. When it restarts, tinfoil-js notices on the next request (the
// old key no longer works), verifies the enclave again and retries; its verification document then
// carries the new key. So comparing the key a response came over with the key the statement came over
// says whether both come from the same boot, and so from the same adapter, which can only change with
// a restart.

import { SecureClient, type VerificationDocument } from 'tinfoil'

const ENCLAVE_URL: string | undefined = import.meta.env.VITE_ENCLAVE_URL
const CONFIG_REPO: string | undefined = import.meta.env.VITE_CONFIG_REPO

export type Connection = {
  fetch: typeof fetch
  /** The enclave's attestation as tinfoil-js last verified it: null when nothing is verified (local twin or mock). */
  verification: () => VerificationDocument | null
}

/** Which boot of the enclave the connection talks to: the key it encrypts to. null without an enclave. */
export function boot(connection: Connection): string | null {
  return connection.verification()?.hpkePublicKey || null
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

/** Forget the connection: the next request verifies the enclave again, e.g. after it restarted
 * with a new key. */
export function disconnect(): void {
  connecting = null
}

async function open(): Promise<Connection> {
  if (!ENCLAVE_URL) return { fetch: (input, init) => fetch(input, init), verification: () => null }
  if (!CONFIG_REPO) throw new Error('VITE_ENCLAVE_URL needs VITE_CONFIG_REPO: the repo whose release the enclave must run')
  const client = new SecureClient({ enclaveURL: ENCLAVE_URL, configRepo: CONFIG_REPO,
                                    baseURL: import.meta.env.DEV ? window.location.origin : undefined })
  await client.ready()
  return { fetch: client.fetch, verification: () => client.getVerificationDocument() }
}
