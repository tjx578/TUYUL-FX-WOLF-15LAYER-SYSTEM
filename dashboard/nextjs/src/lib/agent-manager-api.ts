// ============================================================
// TUYUL FX Wolf-15 — Agent Manager API Hooks & Mutations
// Connects to: /api/v1/agent-manager/* (Phase 2 backend)
// Self-contained: replicates fetcher pattern from @/lib/api
// ============================================================

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { bearerHeader } from "@/lib/auth";
import { HttpError } from "@/lib/fetcher";
import { useSessionStore } from "@/store/useSessionStore";
import type {
  AgentItem,
  AgentListResponse,
  AgentRuntime,
  AgentEvent,
  AgentAuditLog,
  AgentProfile,
  PortfolioSnapshot,
  AgentListFilters,
  CreateAgentRequest,
  UpdateAgentRequest,
  LockAgentRequest,
  CreateProfileRequest,
} from "@/types/agent-manager";

// Global 429 cooldown for agent-manager API calls
let _amRateLimitedUntil = 0;

export const AGENT_MANAGER_ENDPOINTS = {
  agents: "/api/v1/agent-manager/agents",
  agentById: (id: string) => `/api/v1/agent-manager/agents/${id}`,
  agentRuntime: (id: string) => `/api/v1/agent-manager/agents/${id}/runtime`,
  agentEvents: (id: string) => `/api/v1/agent-manager/agents/${id}/events`,
  agentAudit: (id: string) => `/api/v1/agent-manager/agents/${id}/audit`,
  agentLock: (id: string) => `/api/v1/agent-manager/agents/${id}/lock`,
  agentUnlock: (id: string) => `/api/v1/agent-manager/agents/${id}/unlock`,
  agentSnapshots: (id: string) => `/api/v1/agent-manager/agents/${id}/snapshots`,
  profiles: "/api/v1/agent-manager/profiles",
} as const;

// ─── Internal Fetch Helpers ───────────────────────────────────

const amFetcher = async (url: string) => {
  if (useSessionStore.getState().expiredReason) {
    throw new HttpError("Session expired", 401);
  }

  if (_amRateLimitedUntil > Date.now()) {
    throw new HttpError("Rate limited — waiting for cooldown", 429);
  }

  const auth = bearerHeader();
  const res = await fetch(url, {
    credentials: "include",
    headers: {
      ...(auth ? { Authorization: auth } : {}),
    },
  });

  if (res.status === 429) {
    const retryAfter = res.headers.get("Retry-After");
    _amRateLimitedUntil = Date.now() + (retryAfter ? parseInt(retryAfter, 10) * 1000 : 60_000);
    throw new HttpError("Rate limited", 429);
  }

  if (!res.ok) {
    let info: unknown = null;
    try {
      info = await res.json();
    } catch {
      try {
        info = await res.text();
      } catch {
        info = null;
      }
    }
    throw new HttpError(`Request failed: ${res.status} ${res.statusText}`, res.status, info);
  }

  return res.json();
};

const amMutate = async (url: string, body?: unknown, method = "POST") => {
  const governanceHeaders: Record<string, string> =
    method.toUpperCase() === "GET"
      ? {}
      : {
          "X-Edit-Mode": "ON",
          "X-Action-Reason": "UI_WRITE_ACTION",
          ...(process.env.NEXT_PUBLIC_ACTION_PIN
            ? { "X-Action-Pin": process.env.NEXT_PUBLIC_ACTION_PIN }
            : {}),
        };

  const auth = bearerHeader();
  const res = await fetch(url, {
    method,
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...(auth ? { Authorization: auth } : {}),
      ...governanceHeaders,
    },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });

  if (!res.ok) {
    let info: unknown = null;
    try {
      info = await res.json();
    } catch {
      try {
        info = await res.text();
      } catch {
        info = null;
      }
    }
    throw new HttpError(`Request failed: ${res.status} ${res.statusText}`, res.status, info);
  }

  return res.json().catch(() => undefined);
};

// ─── Internal Query Helper ────────────────────────────────────

function useAmQuery<T>(key: string | null, opts?: { refetchInterval?: number }) {
  const queryClient = useQueryClient();
  const { data, error, isLoading } = useQuery<T>({
    queryKey: [key],
    queryFn: () => amFetcher(key!),
    enabled: !!key,
    ...(opts?.refetchInterval ? { refetchInterval: opts.refetchInterval } : {}),
  });
  const mutate = () => queryClient.invalidateQueries({ queryKey: [key] });
  return { data, isLoading, isError: !!error, error, mutate };
}

// ─── HOOKS ────────────────────────────────────────────────────

export function useAgentManagerList(filters?: AgentListFilters) {
  const params = new URLSearchParams();
  if (filters?.ea_class) params.set("ea_class", filters.ea_class);
  if (filters?.status) params.set("status", filters.status);
  if (filters?.limit !== undefined) params.set("limit", String(filters.limit));
  if (filters?.offset !== undefined) params.set("offset", String(filters.offset));

  const query = params.toString();
  const url = query
    ? `${AGENT_MANAGER_ENDPOINTS.agents}?${query}`
    : AGENT_MANAGER_ENDPOINTS.agents;

  const { data, isLoading, isError, error, mutate } = useAmQuery<AgentListResponse>(
    url,
    { refetchInterval: 10_000 },
  );
  return {
    data: data?.agents ?? [],
    total: data?.total ?? 0,
    isLoading,
    isError,
    error,
    mutate,
  };
}

export function useAgentManagerDetail(agentId: string | null) {
  const url = agentId ? AGENT_MANAGER_ENDPOINTS.agentById(agentId) : null;
  const { data, isLoading, isError, error, mutate } = useAmQuery<AgentItem>(url, {
    refetchInterval: 10_000,
  });
  return { data, isLoading, isError, error, mutate };
}

export function useAgentManagerRuntime(agentId: string | null) {
  const url = agentId ? AGENT_MANAGER_ENDPOINTS.agentRuntime(agentId) : null;
  const { data, isLoading, isError, error, mutate } = useAmQuery<AgentRuntime>(url, {
    refetchInterval: 10_000,
  });
  return { data, isLoading, isError, error, mutate };
}

export function useAgentManagerEvents(agentId: string | null, limit?: number) {
  let url: string | null = null;
  if (agentId) {
    const base = AGENT_MANAGER_ENDPOINTS.agentEvents(agentId);
    url = limit !== undefined ? `${base}?limit=${limit}` : base;
  }
  const { data, isLoading, isError, error, mutate } = useAmQuery<{
    events: AgentEvent[];
    total: number;
  }>(url);
  return { data: data?.events ?? [], total: data?.total ?? 0, isLoading, isError, error, mutate };
}

export function useAgentManagerAudit(agentId: string | null, limit?: number) {
  let url: string | null = null;
  if (agentId) {
    const base = AGENT_MANAGER_ENDPOINTS.agentAudit(agentId);
    url = limit !== undefined ? `${base}?limit=${limit}` : base;
  }
  const { data, isLoading, isError, error, mutate } = useAmQuery<{
    logs: AgentAuditLog[];
    total: number;
  }>(url);
  return { data: data?.logs ?? [], total: data?.total ?? 0, isLoading, isError, error, mutate };
}

export function useAgentManagerProfiles() {
  const { data, isLoading, isError, error, mutate } = useAmQuery<AgentProfile[]>(
    AGENT_MANAGER_ENDPOINTS.profiles,
  );
  return { data: data ?? [], isLoading, isError, error, mutate };
}

export function useAgentManagerSnapshots(agentId: string | null, limit?: number) {
  let url: string | null = null;
  if (agentId) {
    const base = AGENT_MANAGER_ENDPOINTS.agentSnapshots(agentId);
    url = limit !== undefined ? `${base}?limit=${limit}` : base;
  }
  const { data, isLoading, isError, error, mutate } = useAmQuery<PortfolioSnapshot[]>(url);
  return { data: data ?? [], isLoading, isError, error, mutate };
}

// ─── MUTATIONS ────────────────────────────────────────────────

export async function createAgent(data: CreateAgentRequest): Promise<AgentItem> {
  return amMutate(AGENT_MANAGER_ENDPOINTS.agents, data, "POST");
}

export async function updateAgent(agentId: string, data: UpdateAgentRequest): Promise<AgentItem> {
  return amMutate(AGENT_MANAGER_ENDPOINTS.agentById(agentId), data, "PUT");
}

export async function deleteAgent(agentId: string): Promise<void> {
  await amMutate(AGENT_MANAGER_ENDPOINTS.agentById(agentId), undefined, "DELETE");
}

export async function lockAgent(agentId: string, data: LockAgentRequest): Promise<AgentItem> {
  return amMutate(AGENT_MANAGER_ENDPOINTS.agentLock(agentId), data, "POST");
}

export async function unlockAgent(agentId: string): Promise<AgentItem> {
  return amMutate(AGENT_MANAGER_ENDPOINTS.agentUnlock(agentId), undefined, "POST");
}

export async function createProfile(data: CreateProfileRequest): Promise<AgentProfile> {
  return amMutate(AGENT_MANAGER_ENDPOINTS.profiles, data, "POST");
}
