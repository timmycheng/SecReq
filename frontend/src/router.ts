/* 极简 hash 路由: #/ 项目列表, #/wizard/:id 向导, #/result/:id 产物页。 */
import { useEffect, useState } from 'react'

export type Route =
  | { name: 'list' }
  | { name: 'wizard'; projectId: number }
  | { name: 'result'; projectId: number }

export function parseHash(hash: string): Route {
  const path = hash.replace(/^#\/?/, '')
  const parts = path.split('/').filter(Boolean)
  if (parts[0] === 'wizard' && parts[1]) return { name: 'wizard', projectId: Number(parts[1]) }
  if (parts[0] === 'result' && parts[1]) return { name: 'result', projectId: Number(parts[1]) }
  return { name: 'list' }
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
