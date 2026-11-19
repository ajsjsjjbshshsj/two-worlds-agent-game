export const account = { id: 'account_fixture', email: 'player@example.test', display_name: '旅人' }
export const session = { expires_at: '2027-01-01T00:00:00Z' }
export const me = { account, session }
export const other = {
  account: { id: 'account_other', email: 'partner@example.test', display_name: '搭档' },
  session,
}
export const password = 'example-password-123'
export const loginInput = { email: account.email, password }
export const registerInput = { ...loginInput, code: '123456', display_name: '旅人' }
export const resetInput = { email: account.email, code: '123456', new_password: password }

export function json(body: unknown, status = 200, headers?: HeadersInit) {
  return new Response(JSON.stringify(body), { status, headers })
}
export function fail(status: number, code = 'UNAUTHENTICATED', seconds?: string) {
  return json(
    {
      error: {
        code,
        message: 'PRIVATE_TEST_RESPONSE',
        retryable: status === 429 || status === 503,
      },
    },
    status,
    seconds === undefined ? undefined : { 'Retry-After': seconds },
  )
}
export function noContent() {
  return new Response(null, { status: 204 })
}
export function deferred<T>() {
  let resolve!: (v: T) => void
  const promise = new Promise<T>((done) => {
    resolve = done
  })
  return { promise, resolve }
}
