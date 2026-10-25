import { defineConfig } from "@hey-api/openapi-ts";

export default defineConfig({
  input: "../docs/v2/openapi.json",
  output: "src/api",
  plugins: ["@hey-api/client-fetch", "@tanstack/react-query"],
});
