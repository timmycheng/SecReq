/* 自研 hash 路由(#280 改版): #/ 工作台, #/systems 系统清单, #/systems/:id 系统详情,
   #/evaluations 评估清单, #/evaluations/:id/wizard 问卷, #/evaluations/:id/result 产物页,
   #/evaluations/:id/review 评审页, #/reviews 评审中心(#307); 平台设置组:
   /admin(系统设置) /vulndb(漏洞库) /filings /knowledge /users /ldap /llm /netbox /audit /changelog。 */
import { useEffect, useState } from 'react'

export type Route =
  | { name: 'dashboard' }
  | { name: 'systems' }
  | { name: 'systemDetail'; systemId: number }
  | { name: 'evaluations' }
  | { name: 'reviews' }
  | { name: 'wizard'; projectId: number }
  | { name: 'result'; projectId: number }
  | { name: 'review'; projectId: number }
  | { name: 'admin' }
  | { name: 'vulndb' }
  | { name: 'filings' }
  | { name: 'knowledge' }
  | { name: 'users' }
  | { name: 'ldap' }
  | { name: 'llm' }
  | { name: 'netbox' }
  | { name: 'audit' }
  | { name: 'changelog' }

const NAMED_SEGMENTS: Record<string, Route> = {
  systems: { name: 'systems' },
  evaluations: { name: 'evaluations' },
  reviews: { name: 'reviews' },
  admin: { name: 'admin' },
  vulndb: { name: 'vulndb' },
  filings: { name: 'filings' },
  knowledge: { name: 'knowledge' },
  users: { name: 'users' },
  ldap: { name: 'ldap' },
  llm: { name: 'llm' },
  netbox: { name: 'netbox' },
  audit: { name: 'audit' },
  changelog: { name: 'changelog' },
}

export function parseHash(hash: string): Route {
  const parts = hash.replace(/^#\/?/, '').split('/').filter(Boolean)
  const [head, second, third] = parts
  if (head === 'systems' && second) return { name: 'systemDetail', systemId: Number(second) }
  if (head === 'evaluations' && second) {
    const projectId = Number(second)
    if (third === 'wizard') return { name: 'wizard', projectId }
    if (third === 'review') return { name: 'review', projectId }
    return { name: 'result', projectId }
  }
  if (head && NAMED_SEGMENTS[head]) return NAMED_SEGMENTS[head]
  return { name: 'dashboard' }
}

export function navigate(path: string) {
  window.location.hash = path
}

export function useRoute(): Route {
  const [route, setRoute] = useState<Route>(() => parseHash(window.location.hash))
  useEffect(() => {
    const onChange = () => setRoute(parseHash(window.location.hash))
    window.addEventListener('hashchange', onChange)
    return () => window.removeEventListener('hashchange', onChange)
  }, [])
  return route
}
