const LEGACY_RECOVERY_REMINDER = /^twoworlds\.recovery\.pending\.v1\.[a-z][a-z0-9_]{0,63}$/

export function clearLegacyIdentityStorage() {
  try {
    const storage = window.sessionStorage
    storage.removeItem('twoworlds.session.token')
    storage.removeItem('twoworlds.recovery.pending')
  } catch {
    // Storage settings must not prevent Cookie authentication from starting.
  }

  try {
    const storage = window.localStorage
    const reminders: string[] = []
    for (let index = 0; index < storage.length; index++) {
      const key = storage.key(index)
      // The retired client wrote this namespace only with validated account IDs.
      if (key && LEGACY_RECOVERY_REMINDER.exec(key)?.[0] === key) reminders.push(key)
    }
    for (const key of reminders) storage.removeItem(key)
  } catch {
    // Keep the two stores independent so one denied store cannot block the other.
  }
}
