import { useQuery } from "@tanstack/react-query";

import { runsService } from "~/services/runs";

export const runKeys = {
  detail: (id: number) => ["runs", id] as const,
};

// Polls while the run is still pending/running, stops once it settles.
export function useRun(id: number) {
  return useQuery({
    queryKey: runKeys.detail(id),
    queryFn: () => runsService.get(id),
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === "pending" || status === "running" ? 1000 : false;
    },
  });
}
