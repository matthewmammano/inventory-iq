import { createBrowserRouter } from "react-router";

import { V2_BASENAME } from "../constants";
import { ScanScreen } from "./scan/ScanScreen";

export const router = createBrowserRouter([{ path: "/", element: <ScanScreen /> }], { basename: V2_BASENAME });
