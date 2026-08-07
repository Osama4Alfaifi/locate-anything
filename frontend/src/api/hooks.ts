import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "./client";

export function useHealth() {
  return useQuery({
    queryKey: ["health"],
    queryFn: api.health,
    // Poll quickly while the model loads so the UI flips to ready promptly.
    refetchInterval: (query) => (query.state.data?.status === "loading" ? 2000 : 15000),
  });
}

export function useTasks() {
  return useQuery({ queryKey: ["tasks"], queryFn: api.tasks, staleTime: Infinity });
}

export function useDevices() {
  return useQuery({ queryKey: ["devices"], queryFn: api.devices, refetchInterval: 15000 });
}

export function useSwitchDevice() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: api.setDevice,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["devices"] });
      qc.invalidateQueries({ queryKey: ["health"] });
    },
  });
}

export function useHistory() {
  return useQuery({ queryKey: ["history"], queryFn: () => api.history() });
}

export function useHistoryItem(id: string | null) {
  return useQuery({
    queryKey: ["history", id],
    queryFn: () => api.historyItem(id as string),
    enabled: !!id,
  });
}

export function useLocate() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: api.locate,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["history"] }),
  });
}

export function useDeleteHistory() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: api.deleteHistory,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["history"] }),
  });
}

export function useUploadClip() {
  return useMutation({ mutationFn: api.uploadClip });
}

export function useClips() {
  return useQuery({ queryKey: ["clips"], queryFn: () => api.listClips() });
}

export function useClip(id: string | null) {
  return useQuery({
    queryKey: ["clip", id],
    queryFn: () => api.getClip(id as string),
    enabled: !!id,
    // Poll while frame extraction is in flight so the UI flips to "ready" promptly.
    refetchInterval: (query) => (query.state.data?.status === "extracting" ? 1000 : false),
  });
}

export function useDeleteClip() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: api.deleteClip,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["clips"] }),
  });
}

export function useStartClipSearch() {
  return useMutation({
    mutationFn: ({ clipId, form }: { clipId: string; form: FormData }) =>
      api.startClipSearch(clipId, form),
  });
}

export function useClipSearch(clipId: string | null, searchId: string | null) {
  return useQuery({
    queryKey: ["clipSearch", clipId, searchId],
    queryFn: () => api.getClipSearch(clipId as string, searchId as string),
    enabled: !!clipId && !!searchId,
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === "queued" || status === "running" ? 1000 : false;
    },
  });
}

export function useCancelClipSearch() {
  return useMutation({
    mutationFn: ({ clipId, searchId }: { clipId: string; searchId: string }) =>
      api.cancelClipSearch(clipId, searchId),
  });
}
