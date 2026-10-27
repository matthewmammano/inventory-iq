import { createBrowserRouter } from "react-router";

import { ADMIN_PATH, SCAN_PATH, SIGN_IN_PATH, V2_BASENAME } from "../constants";
import { AdminUnlock } from "./admin/AdminUnlock";
import { ScanFlow } from "./scan/ScanFlow";
import { SignInScreen } from "./signIn/SignInScreen";

export const router = createBrowserRouter(
  [
    { path: SCAN_PATH, element: <ScanFlow /> },
    { path: SIGN_IN_PATH, element: <SignInScreen /> },
    { path: ADMIN_PATH, element: <AdminUnlock /> },
  ],
  { basename: V2_BASENAME },
);
