import { NextResponse } from 'next/server'
import type { NextRequest } from 'next/server'

export function middleware(req: NextRequest) {
  // Only protect the root and incident pages
  const url = req.nextUrl.clone()
  if (url.pathname.startsWith('/api') || url.pathname.startsWith('/_next')) {
    return NextResponse.next()
  }

  const basicAuth = req.headers.get('authorization')
  
  if (basicAuth) {
    const authValue = basicAuth.split(' ')[1]
    const [user, pwd] = atob(authValue).split(':')

    const validUser = process.env.BASIC_AUTH_USER || 'admin'
    const validPass = process.env.BASIC_AUTH_PASSWORD || 'swarm2026'

    if (user === validUser && pwd === validPass) {
      return NextResponse.next()
    }
  }
  
  url.pathname = '/api/auth'
  
  return new NextResponse('Auth Required', {
    status: 401,
    headers: {
      'WWW-Authenticate': 'Basic realm="Secure Area"',
    },
  })
}
