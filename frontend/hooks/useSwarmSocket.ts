import { useEffect, useReducer, useRef } from "react";
import {
  AgentName,
  AgentStatus,
  IncidentUIState,
  SwarmEvent,
} from "../lib/types";

const initialIncidentState: IncidentUIState = {
  incident: null,
  agentStatuses: {
    commander: "idle",
    log_forensics: "idle",
    telemetry_intel: "idle",
    deployment_intel: "idle",
    consensus_engine: "idle",
    postmortem_intel: "idle",
    safety_validator: "idle",
  },
  evidenceNodes: [],
  findings: [],
  conflicts: [],
  consensus: null,
  pendingApprovals: [],
  postmortem: null,
  events: [],
  connectionStatus: "disconnected",
  similarPastIncidents: [],
  timeline: [],
};

type Action =
  | { type: "SET_CONNECTION_STATUS"; payload: IncidentUIState["connectionStatus"] }
  | { type: "PROCESS_EVENT"; payload: SwarmEvent };

function incidentReducer(state: IncidentUIState, action: Action): IncidentUIState {
  if (action.type === "SET_CONNECTION_STATUS") {
    return { ...state, connectionStatus: action.payload };
  }

  if (action.type === "PROCESS_EVENT") {
    const event = action.payload;
    const nextState = { ...state, events: [...state.events, event] };

    switch (event.event) {
      case "incident_state_sync": {
        const syncPayload = event.payload as any;
        const syncedIncident = syncPayload.incident || nextState.incident;
        
        // Derive agent statuses from the incident document if available
        const syncedStatuses = { ...nextState.agentStatuses };
        if (syncedIncident?.agent_statuses) {
          for (const [key, value] of Object.entries(syncedIncident.agent_statuses)) {
            syncedStatuses[key as AgentName] = value as AgentStatus;
          }
        }
        // If incident is still active, set commander to investigating
        if (syncedIncident?.status === "investigating" || syncedIncident?.status === "awaiting_approval") {
          syncedStatuses.commander = "investigating";
        } else if (syncedIncident?.status === "resolved") {
          // If resolved, ensure all agents are marked as done so the UI reflects completion
          Object.keys(syncedStatuses).forEach(agent => {
            syncedStatuses[agent as AgentName] = "done";
          });
        }
        
        // Extract conflicts from state sync
        const syncedConflicts = syncPayload.conflicts || nextState.conflicts || [];

        return {
          ...nextState,
          incident: syncedIncident,
          timeline: syncPayload.timeline || [],
          findings: syncPayload.agent_findings || [],
          evidenceNodes: syncPayload.evidence_nodes || [],
          agentStatuses: syncedStatuses,
          postmortem: syncPayload.postmortem || null,
          consensus: syncPayload.consensus || null,
          conflicts: syncedConflicts,
        };
      }
      case "agent_status_change": {
        const payload = event.payload as any;
        const newTimeline = [...nextState.timeline, {
          timestamp: new Date().toISOString(),
          event: `Status changed to ${payload.status}`,
          agent: payload.agent_id as AgentName,
          round_number: null,
        }];
        return {
          ...nextState,
          timeline: newTimeline,
          agentStatuses: {
            ...nextState.agentStatuses,
            [payload.agent_id]: payload.status,
          },
        };
      }
      case "evidence_added": {
        return {
          ...nextState,
          evidenceNodes: [...nextState.evidenceNodes, event.payload as any],
        };
      }
      case "finding_added": {
        return {
          ...nextState,
          findings: [...nextState.findings, event.payload as any],
        };
      }
      case "conflict_detected": {
        return {
          ...nextState,
          conflicts: [...nextState.conflicts, event.payload as any],
        };
      }
      case "challenge_resolved": {
         // Optionally remove the conflict or update finding confidence based on target_finding_id
         return nextState;
      }
      case "consensus_reached": {
        const newTimeline = [...nextState.timeline, {
          timestamp: new Date().toISOString(),
          event: "Consensus reached successfully",
          agent: "consensus_engine" as AgentName,
          round_number: null,
        }];
        // Mark all existing conflicts as resolved instead of clearing them
        const resolvedConflicts = nextState.conflicts.map(c => ({ ...c, resolved: true }));
        // Also capture any conflicts from the consensus payload itself
        const consensusPayload = event.payload as any;
        const payloadConflicts = (consensusPayload?.conflicts || []).map((c: any) => ({ ...c, resolved: true }));
        // Merge: keep existing resolved conflicts + any new ones from consensus
        const existingIds = new Set(resolvedConflicts.map(c => c.id));
        const mergedConflicts = [
          ...resolvedConflicts,
          ...payloadConflicts.filter((c: any) => !existingIds.has(c.id)),
        ];
        return {
          ...nextState,
          timeline: newTimeline,
          consensus: consensusPayload,
          conflicts: mergedConflicts,
          agentStatuses: {
            ...nextState.agentStatuses,
            consensus_engine: "done",
          }
        };
      }
      case "approval_requested": {
        const newTimeline = [...nextState.timeline, {
          timestamp: new Date().toISOString(),
          event: "Human approval requested for high-risk action",
          agent: "safety_validator" as AgentName,
          round_number: null,
        }];
        return {
          ...nextState,
          timeline: newTimeline,
          pendingApprovals: [...nextState.pendingApprovals, event.payload as any],
          incident: nextState.incident ? { ...nextState.incident, status: "awaiting_approval" } : null,
          agentStatuses: {
            ...nextState.agentStatuses,
            safety_validator: "done",
          }
        };
      }
      case "approval_response": {
        const payload = event.payload as any;
        const newTimeline = [...nextState.timeline, {
          timestamp: new Date().toISOString(),
          event: `Human approval ${payload.decision}`,
          agent: "safety_validator" as AgentName,
          round_number: null,
        }];
        return {
          ...nextState,
          timeline: newTimeline,
          pendingApprovals: nextState.pendingApprovals.filter(a => a.id !== payload.approval_id),
        };
      }
      case "postmortem_ready": {
        const newTimeline = [...nextState.timeline, {
           timestamp: new Date().toISOString(),
           event: "Postmortem report generated",
           agent: "postmortem_intel" as AgentName,
           round_number: null,
        }];
        return {
          ...nextState,
          timeline: newTimeline,
          postmortem: event.payload as any,
          incident: nextState.incident ? { ...nextState.incident, status: "resolved" } : null,
          agentStatuses: {
            ...nextState.agentStatuses,
            postmortem_intel: "done",
            commander: "done",
          }
        };
      }
      case "incident_resolved": {
        return {
          ...nextState,
          incident: nextState.incident ? { ...nextState.incident, status: "resolved" } : null,
          agentStatuses: {
            ...nextState.agentStatuses,
            commander: "done",
          }
        };
      }
      case "incident_created": {
        const payload = event.payload as any;
        return {
          ...nextState,
          incident: payload.incident || payload,
        };
      }
      case "memory_recalled": {
        return {
          ...nextState,
          similarPastIncidents: (event.payload as any).similar_incidents || [],
        };
      }
      case "timeline_updated": {
        const tlPayload = event.payload as any;
        return {
          ...nextState,
          timeline: [...nextState.timeline, {
            timestamp: tlPayload.timestamp || new Date().toISOString(),
            event: tlPayload.event,
            agent: tlPayload.agent as AgentName,
            round_number: tlPayload.round_number || null,
          }],
        };
      }
      case "ping": {
        // Handled by socket directly for pong, but logged here
        return nextState;
      }
      default:
        return nextState;
    }
  }

  return state;
}

export function useSwarmSocket(incidentId: string) {
  const [state, dispatch] = useReducer(incidentReducer, initialIncidentState);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const retryCountRef = useRef(0);

  useEffect(() => {
    if (!incidentId) return;

    const connect = () => {
      dispatch({ type: "SET_CONNECTION_STATUS", payload: "connecting" });
      const WS_URL = process.env.NEXT_PUBLIC_WS_URL ?? "ws://localhost:8000";
      const ws = new WebSocket(`${WS_URL}/api/ws/incidents/${incidentId}`);

      ws.onopen = () => {
        dispatch({ type: "SET_CONNECTION_STATUS", payload: "connected" });
        retryCountRef.current = 0; // reset retry logic
      };

      ws.onmessage = (message) => {
        try {
          const event: SwarmEvent = JSON.parse(message.data);
          
          if (event.event === "ping") {
            // Send pong back immediately
            ws.send(JSON.stringify({ event: "pong" }));
            return;
          }
          
          dispatch({ type: "PROCESS_EVENT", payload: event });
        } catch (e) {
          console.error("Failed to parse websocket message", e);
        }
      };

      ws.onclose = () => {
        dispatch({ type: "SET_CONNECTION_STATUS", payload: "disconnected" });
        
        // Exponential backoff reconnect
        const backoff = Math.min(1000 * Math.pow(2, retryCountRef.current), 30000);
        retryCountRef.current += 1;
        
        reconnectTimeoutRef.current = setTimeout(connect, backoff);
      };

      ws.onerror = (error) => {
        dispatch({ type: "SET_CONNECTION_STATUS", payload: "error" });
      };

      wsRef.current = ws;
    };

    connect();

    return () => {
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
      }
      if (wsRef.current) {
        wsRef.current.close();
      }
    };
  }, [incidentId]);

  const sendApprovalResponse = (actionId: string, approved: boolean, note?: string) => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(
        JSON.stringify({
          event: "approval_response",
          payload: { action_id: actionId, approved, note },
        })
      );
    } else {
      console.error("WebSocket is not connected. Cannot send approval response.");
    }
  };

  return { state, sendApprovalResponse };
}
