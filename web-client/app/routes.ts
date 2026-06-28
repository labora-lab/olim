import {
  type RouteConfig,
  index,
  layout,
  route,
} from "@react-router/dev/routes";

export default [
  // Shell with the dataset sidebar — no URL segment of its own.
  layout("routes/shell.tsx", [
    index("routes/datasets-index.tsx"),
    route("datasets/:datasetId", "routes/dataset.tsx", [
      index("routes/dataset-index.tsx"),
      route("annotate", "routes/annotate.tsx"),
      route("pipelines", "routes/pipelines.tsx"),
    ]),
  ]),
] satisfies RouteConfig;
