import { createBrowserRouter } from "react-router";

import { ScanScreen } from "./scan/ScanScreen";

export const router = createBrowserRouter([{ path: "/", element: <ScanScreen /> }]);
