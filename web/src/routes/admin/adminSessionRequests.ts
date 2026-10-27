import {
  postApiV1AgenciesByAgencyIdAdminSession,
  postApiV1AgenciesByAgencyIdAdminSessionTemporaryPin,
} from "../../api/sdk.gen";
import { TEMPORARY_PIN_FAILED_NOTE, UNLOCK_UNREACHABLE_NOTE } from "../../constants";
import { apiRefusal } from "../../lib/apiRefusal";

/** A wrong PIN, an unknown agency and a rate-limited attempt all arrive as a refusal the API worded. */
export type AdminSessionResult = { kind: "ok" } | { kind: "refused"; message: string };

type Answered<E> = { error: E | undefined; response?: Response };

function outcome<E extends { message?: string }>(answer: Answered<E>, unreachableMessage: string): AdminSessionResult {
  if (answer.error === undefined) return { kind: "ok" };
  return { kind: "refused", message: apiRefusal(answer, unreachableMessage).message };
}

export async function requestAdminUnlock(attempt: { agencyId: number; pin: string }): Promise<AdminSessionResult> {
  const answer = await postApiV1AgenciesByAgencyIdAdminSession({
    path: { agency_id: attempt.agencyId },
    body: { pin: attempt.pin },
  });
  return outcome(answer, UNLOCK_UNREACHABLE_NOTE);
}

export async function requestTemporaryPin(agencyId: number): Promise<AdminSessionResult> {
  const answer = await postApiV1AgenciesByAgencyIdAdminSessionTemporaryPin({ path: { agency_id: agencyId } });
  return outcome(answer, TEMPORARY_PIN_FAILED_NOTE);
}
