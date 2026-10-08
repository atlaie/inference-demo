// The eval's receipt. Until the registry reads receipt/v3 (Chris's PySyft adapter), the app uses
// OpenMined's example receipt from ../fixtures; later this fetches it from the registry's read API.

import example from '../../../fixtures/receipt-v3.json'
import type { Pipeline } from './compare'

export type Metric = { name: string; value: number; unit?: string; n?: number; higherIsBetter?: boolean }

export type Receipt = {
  subject: { name: string; digest: { sha256: string } }[]
  predicateType: string
  predicate: {
    evalPipeline: Pipeline
    evalDataset?: { name: string; digest: string; scheme: string; owner?: string }
    execution: { finishedAt: string; startedAt: string; platform?: string;
                 attestation: { referenceValue: { repo: string; tag: string } } }
    results: { counts?: { submitted: number; completed: number; failed: number }; metrics: Metric[] }
  }
}

export const receipt = example as unknown as Receipt

// Where the registry's UI is; the record pages are still being built.
const REGISTRY_URL = import.meta.env.VITE_REGISTRY_URL ?? 'http://localhost:5173'

export function registryLink(r: Receipt): string {
  return `${REGISTRY_URL}/lookup/${r.subject[0].digest.sha256}`
}
