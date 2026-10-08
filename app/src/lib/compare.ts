// The eval-vs-inference comparison: a port of sash_inference.compare, which is the reference.

export type Alias = { scheme: string; ref?: string; digest?: string }

export type Component = {
  id: string
  role: string
  name?: string
  scheme: string
  digest: string
  alsoKnownAs?: Alias[] | null
  params?: Record<string, unknown>
  appliesTo?: string[]
}

export type ConfigEntry = Component & { kind?: string; enforced?: boolean }

export type Pipeline = { models: Component[]; config: ConfigEntry[] }

export type Verdict = 'match' | 'differs' | 'not served' | 'not evaluated' | 'eval only'

export type Row = {
  id: string
  role: string
  name?: string
  verdict: Verdict
  on: string[] // the schemes the two sides share an identifier under
  evaluated?: Component
  served?: Component
  enforced?: boolean
}

const WEIGHT_ROLES = ['base', 'adapter']

/** Every (scheme, value) a component is known by: its digest and its aliases, as "scheme value". */
export function identifiers(component: Component): Set<string> {
  const ids = new Set([`${component.scheme} ${component.digest}`])
  for (const alias of component.alsoKnownAs ?? []) ids.add(`${alias.scheme} ${alias.digest ?? alias.ref}`)
  return ids
}

function shared(a: Component, b: Component): string[] {
  const other = identifiers(b)
  return [...identifiers(a)].filter((id) => other.has(id)).map((id) => id.split(' ')[0]).sort()
}

export function compare(evaluated: Pipeline, served: Pipeline): Row[] {
  const servedModels = new Map(served.models.map((m) => [m.role, m]))
  const rows: Row[] = []
  for (const model of evaluated.models) {
    const row = { id: model.id, role: model.role, name: model.name, evaluated: model, on: [] as string[] }
    const counterpart = servedModels.get(model.role)
    if (!WEIGHT_ROLES.includes(model.role)) rows.push({ ...row, verdict: 'eval only' })
    else if (!counterpart) rows.push({ ...row, verdict: 'not served' })
    else {
      const on = shared(model, counterpart)
      rows.push({ ...row, served: counterpart, on, verdict: on.length ? 'match' : 'differs' })
    }
  }
  const evaluatedRoles = new Set(evaluated.models.map((m) => m.role))
  for (const [role, model] of servedModels) {
    if (!evaluatedRoles.has(role)) rows.push({ id: model.id, role, name: model.name, served: model, on: [], verdict: 'not evaluated' })
  }
  const servedConfig = new Map(served.config.map((c) => [c.id, c]))
  for (const config of evaluated.config) {
    const counterpart = servedConfig.get(config.id)
    const row = { id: config.id, role: config.kind ?? config.id, evaluated: config }
    if (!counterpart) rows.push({ ...row, on: [], verdict: 'not served' })
    else {
      const same = counterpart.scheme === config.scheme && counterpart.digest === config.digest
      rows.push({ ...row, served: counterpart, on: same ? [config.scheme] : [], verdict: same ? 'match' : 'differs',
                  enforced: counterpart.enforced ?? false })
    }
  }
  return rows
}
