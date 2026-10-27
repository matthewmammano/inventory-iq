/** The v1 server-rendered routes this app hands off to until Phase 5 replaces them. */

const guestRoot = (agencyId: number) => `/inventory/${agencyId}`;

export const adminPanelUrl = (agencyId: number) => `${guestRoot(agencyId)}/admin-panel`;

/** v1 owns setting a password, so an account without one arrives there with its email filled in. */
export const forgotPasswordUrl = (email: string) => `/forgot-password?email=${encodeURIComponent(email)}`;
