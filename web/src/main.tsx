import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Theme, ToastProvider, TooltipProvider } from "@usefragments/ui";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { RouterProvider } from "react-router/dom";

import "@usefragments/ui/styles";
import "./theme/palette.css";
import "./theme/kiosk.css";
import "./lib/apiClient";

import { QUERY_STALE_MS } from "./constants";
import { router } from "./routes/router";
import { THEME } from "./theme/tokens";

const queryClient = new QueryClient({ defaultOptions: { queries: { staleTime: QUERY_STALE_MS } } });

const container = document.getElementById("root");
if (!container) {
  throw new Error("Missing #root element");
}

createRoot(container).render(
  <StrictMode>
    <Theme {...THEME} mode="light">
      <QueryClientProvider client={queryClient}>
        <TooltipProvider>
          <ToastProvider>
            <RouterProvider router={router} />
          </ToastProvider>
        </TooltipProvider>
      </QueryClientProvider>
    </Theme>
  </StrictMode>,
);
