import { useQuery } from "@tanstack/react-query";

import { getApiV1MeOptions } from "../api/@tanstack/react-query.gen";

/** Who this browser is signed in as. A refusal is the honest answer for a signed-out kiosk, so it is not retried. */
export function useSignedInAgency() {
  return useQuery({ ...getApiV1MeOptions(), retry: false });
}
