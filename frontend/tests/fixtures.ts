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

export const pendingA = {
  account: { id: 'account_a', display_name: '旅人甲' },
  session: { token: 'tw_session_a_TEST', expires_at: '2027-01-01T00:00:00Z' },
  recovery_key: 'tw_recovery_a_TEST',
}
export const pendingB = {
  account: { id: 'account_b', display_name: '旅人乙' },
  session: { token: 'tw_session_b_TEST', expires_at: '2027-01-01T00:00:00Z' },
  recovery_key: 'tw_recovery_b_TEST',
}
export const pendingC = {
  account: { id: 'account_c', display_name: '旅人丙' },
  session: { token: 'tw_session_c_TEST', expires_at: '2027-01-01T00:00:00Z' },
  recovery_key: 'tw_recovery_c_TEST',
}
export const pendingMetadata = (account = pendingA.account) => ({
  account_id: account.id,
  display_name: account.display_name,
  created_at: '2026-11-16T00:00:00.000Z',
  pending: true,
})
