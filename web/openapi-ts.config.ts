import { defineConfig } from "@hey-api/openapi-ts";

export default defineConfig({
  input: "../docs/v2/openapi.json",
  output: { path: "src/api", format: "prettier" },
  plugins: ["@hey-api/client-fetch", "@tanstack/react-query"],
});
