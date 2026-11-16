export const account = { id: 'account_fixture', display_name: '旅人' }
export const session = { token: 'tw_session_TEST_ONLY', expires_at: '2027-01-01T00:00:00Z' }
export const created = { account, session, recovery_key: 'tw_recovery_TEST_ONLY' }
export const recovered = { account, session }
export const me = { account, session: { expires_at: session.expires_at } }
export function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status })
}
export function fail(status: number) {
  return json(
    { error: { code: 'UNAUTHENTICATED', message: '固定测试错误', retryable: false } },
    status,
  )
}
