import { createBrowserRouter } from "react-router";

import { V2_BASENAME } from "../constants";
import { ScanFlow } from "./scan/ScanFlow";

export const router = createBrowserRouter([{ path: "/", element: <ScanFlow /> }], { basename: V2_BASENAME });
