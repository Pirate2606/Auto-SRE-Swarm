import {
  ApprovalDecision,
  ApprovalRequest,
  ConsensusResult,
  EvidenceNode,
  Incident,
  IncidentCreate,
  IncidentCreateResponse,
  IncidentSummary,
  PastIncident,
  Postmortem,
  TimelineEntry,
} from "./types";

export class ApiError extends Error {
  public status: number;
  public detail: any;

  constructor(status: number, message: string, detail: any) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

const BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

async function fetcher<T>(endpoint: string, options: RequestInit = {}): Promise<T> {
  const url = `${BASE_URL}${endpoint}`;
  const headers = {
    "Content-Type": "application/json",
    ...options.headers,
  };

  const response = await fetch(url, { ...options, headers });

  if (!response.ok) {
    let detail = "Unknown error";
    let message = `API request failed with status ${response.status}`;
    try {
      const errorData = await response.json();
      detail = errorData.detail || errorData;
      message = typeof detail === "string" ? detail : JSON.stringify(detail);
    } catch (e) {
      // Ignored
    }
    throw new ApiError(response.status, message, detail);
  }

  return response.json();
}

function GET<T>(endpoint: string) {
  return fetcher<T>(endpoint, { method: "GET" });
}

function POST<T>(endpoint: string, body: any) {
  return fetcher<T>(endpoint, { method: "POST", body: JSON.stringify(body) });
}

function PATCH<T>(endpoint: string, body: any) {
  return fetcher<T>(endpoint, { method: "PATCH", body: JSON.stringify(body) });
}

export const api = {
  incidents: {
    create: (body: IncidentCreate) =>
      POST<IncidentCreateResponse>("/api/incidents", body),
    list: (skip = 0, limit = 20) =>
      GET<IncidentSummary[]>(`/api/incidents?skip=${skip}&limit=${limit}`),
    get: (id: string) => GET<Incident>(`/api/incidents/${id}`),
    patch: (id: string, body: Partial<IncidentCreate>) =>
      PATCH<Incident>(`/api/incidents/${id}`, body),
    getEvidence: (id: string) => GET<EvidenceNode[]>(`/api/incidents/${id}/evidence`),
    getConsensus: (id: string) => GET<ConsensusResult>(`/api/incidents/${id}/consensus`),
    getTimeline: (id: string) => GET<TimelineEntry[]>(`/api/incidents/${id}/timeline`),
    getPostmortem: (id: string) => GET<Postmortem>(`/api/incidents/${id}/postmortem`),
    getApprovals: (id: string) => GET<ApprovalRequest[]>(`/api/incidents/${id}/approvals`),
    submitApproval: (incidentId: string, approvalId: string, decision: ApprovalDecision) =>
      POST<ApprovalRequest>(`/api/incidents/${incidentId}/approvals/${approvalId}`, decision),
  },
  memory: {
    similar: (q: string, top_k = 3) =>
      GET<PastIncident[]>(`/api/memory/similar?q=${encodeURIComponent(q)}&top_k=${top_k}`),
  },
  health: () => GET<{ status: string; llm: boolean }>("/api/health"),
};
