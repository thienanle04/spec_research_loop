import { defineConfig } from "orval";

function stripStreamingPaths(spec: Record<string, unknown> & { paths?: Record<string, unknown> }) {
  if (spec.paths) {
    delete spec.paths["/api/idea/demo/stream"];
    delete spec.paths["/api/research/sessions/{session_id}/nodes/{node}/generate"];
    delete spec.paths["/api/idea/sessions/{session_id}/generate"];
  }
  return spec;
}

export default defineConfig({
  specresearch: {
    input: {
      target: `${process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000"}/openapi.json`,
      override: {
        transformer: stripStreamingPaths,
      },
    },
    output: {
      mode: "split",
      target: "lib/api/generated/endpoints.ts",
      schemas: "lib/api/generated/model",
      client: "react-query",
      httpClient: "fetch",
      clean: true,
      override: {
        mutator: {
          path: "./lib/api/mutator.ts",
          name: "customFetch",
        },
      },
    },
  },
});
