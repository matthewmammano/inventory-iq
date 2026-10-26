/** The v1 server-rendered routes this screen hands off to until Phase 5 replaces them. */

const guestRoot = (agencyId: number) => `/inventory/${agencyId}`;

export const adminLoginUrl = (agencyId: number) => `${guestRoot(agencyId)}/admin`;
