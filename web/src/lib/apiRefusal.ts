/** Every refusal the API writes carries its own message, so a screen shows that instead of inventing one. */
export type ApiRefusal = { status: number | null; message: string };

type FailedRequest = { error: { message?: string } | undefined; response?: Response };

/** A request that never reached the server has no status and no message of its own. */
export function apiRefusal({ error, response }: FailedRequest, unreachableMessage: string): ApiRefusal {
  if (response === undefined) return { status: null, message: unreachableMessage };
  const message = error?.message?.trim();
  return { status: response.status, message: message ? message : unreachableMessage };
}
