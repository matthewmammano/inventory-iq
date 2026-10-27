import { postApiV1Session } from "../../api/sdk.gen";
import type { SignInRequest, SignedInAgencyResponse } from "../../api/types.gen";
import { HTTP_CONFLICT, SIGN_IN_UNREACHABLE_NOTE } from "../../constants";
import { apiRefusal } from "../../lib/apiRefusal";

/**
 * An unknown email, an inactive account and a wrong password all come back as one
 * refusal, so the screen never learns which. Only an account with no password set
 * is a separate answer, because it has somewhere else to go.
 */
export type SignInResult =
  | { kind: "signedIn"; agency: SignedInAgencyResponse }
  | { kind: "refused"; message: string }
  | { kind: "passwordNotSet"; message: string };

export async function requestSignIn(credentials: SignInRequest): Promise<SignInResult> {
  const result = await postApiV1Session({ body: credentials });
  if (result.data !== undefined) return { kind: "signedIn", agency: result.data };

  const refusal = apiRefusal(result, SIGN_IN_UNREACHABLE_NOTE);
  if (refusal.status === HTTP_CONFLICT) return { kind: "passwordNotSet", message: refusal.message };
  return { kind: "refused", message: refusal.message };
}
