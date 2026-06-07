import { useEffect, useRef } from "react";
import { SwarmEvent } from "../lib/types";

function formatEventPayload(event: SwarmEvent) {
  const p = event.payload as any;

  switch (event.event) {
    case "incident_state_sync": {
      const inc = p?.incident;
      if (!inc) return <span className="text-gray-500">Syncing state...</span>;
      return (
        <div className="flex flex-col gap-1">
          <span className="text-gray-200 font-semibold">{inc.title}</span>
          <div className="flex flex-wrap gap-2 text-[10px]">
            <span className="px-1.5 py-0.5 rounded bg-gray-800 text-gray-300">ID: {inc.id}</span>
            <span className={`px-1.5 py-0.5 rounded font-bold ${
              inc.severity === "P1" ? "bg-red-900/60 text-red-400" :
              inc.severity === "P2" ? "bg-orange-900/60 text-orange-400" :
              "bg-gray-800 text-gray-400"
            }`}>{inc.severity}</span>
            <span className="px-1.5 py-0.5 rounded bg-gray-800 text-gray-300 capitalize">{inc.status?.replace("_", " ")}</span>
            <span className="px-1.5 py-0.5 rounded bg-gray-800 text-gray-300">Source: {inc.source}</span>
            {inc.investigation_round != null && (
              <span className="px-1.5 py-0.5 rounded bg-gray-800 text-gray-300">Round {inc.investigation_round}</span>
            )}
            {inc.consensus_confidence != null && (
              <span className="px-1.5 py-0.5 rounded bg-emerald-900/60 text-emerald-400">Confidence: {(inc.consensus_confidence * 100).toFixed(0)}%</span>
            )}
          </div>
          {p.agent_findings?.length > 0 && (
            <span className="text-gray-500 text-[10px] mt-1">
              {p.agent_findings.length} finding{p.agent_findings.length !== 1 ? "s" : ""} loaded
            </span>
          )}
          {p.timeline?.length > 0 && (
            <span className="text-gray-500 text-[10px]">
              {p.timeline.length} timeline event{p.timeline.length !== 1 ? "s" : ""} loaded
            </span>
          )}
        </div>
      );
    }

    case "agent_status_change": {
      const statusColors: Record<string, string> = {
        investigating: "text-yellow-400",
        done: "text-emerald-400",
        idle: "text-gray-500",
        error: "text-red-400",
        challenging: "text-purple-400",
      };
      return (
        <span>
          <span className="text-cyan-400 font-semibold">{p.agent_id?.replace("_", " ")}</span>
          {" → "}
          <span className={statusColors[p.status] || "text-gray-300"}>{p.status}</span>
        </span>
      );
    }

    case "finding_added": {
      return (
        <div className="flex flex-col gap-1">
          <div className="flex items-center gap-2">
            <span className="text-cyan-400 font-semibold">{p.agent?.replace("_", " ")}</span>
            {p.confidence != null && (
              <span className="text-[10px] px-1.5 py-0.5 rounded bg-gray-800 text-emerald-400">
                {(p.confidence * 100).toFixed(0)}% confidence
              </span>
            )}
          </div>
          {p.summary && <span className="text-gray-300">{p.summary}</span>}
          {p.root_cause_hypothesis && (
            <span className="text-gray-500 text-[10px]">Hypothesis: {p.root_cause_hypothesis}</span>
          )}
        </div>
      );
    }

    case "evidence_added": {
      return (
        <div className="flex flex-col gap-1">
          <div className="flex items-center gap-2">
            <span className="text-cyan-400 font-semibold">{p.agent?.replace("_", " ")}</span>
            <span className="text-[10px] px-1.5 py-0.5 rounded bg-gray-800 text-gray-300">{p.evidence_type}</span>
            {p.confidence != null && (
              <span className="text-[10px] px-1.5 py-0.5 rounded bg-gray-800 text-emerald-400">
                {(p.confidence * 100).toFixed(0)}%
              </span>
            )}
          </div>
          {p.summary && <span className="text-gray-300">{p.summary}</span>}
        </div>
      );
    }

    case "conflict_detected": {
      return (
        <div className="flex flex-col gap-1">
          <div className="flex items-center gap-2">
            <span className="text-red-400 font-semibold">{p.agent_a?.replace("_", " ")}</span>
            <span className="text-gray-500">vs</span>
            <span className="text-red-400 font-semibold">{p.agent_b?.replace("_", " ")}</span>
          </div>
          {p.position_a && <span className="text-gray-400 text-[10px]">A: {p.position_a}</span>}
          {p.position_b && <span className="text-gray-400 text-[10px]">B: {p.position_b}</span>}
        </div>
      );
    }

    case "challenge_resolved": {
      return (
        <span>
          <span className="text-purple-400 font-semibold">{p.challenger?.replace("_", " ")}</span>
          {" verdict: "}
          <span className={p.verdict === "AGREE" ? "text-emerald-400" : "text-red-400"}>{p.verdict}</span>
          {p.reasoning && <span className="text-gray-500"> — {p.reasoning}</span>}
        </span>
      );
    }

    case "consensus_reached": {
      return (
        <div className="flex flex-col gap-1">
          {p.hypothesis?.title && <span className="text-emerald-300 font-semibold">{p.hypothesis.title}</span>}
          {p.confidence != null && (
            <span className="text-[10px] text-emerald-400">
              Confidence: {(p.confidence * 100).toFixed(0)}%
            </span>
          )}
          {p.conflicts?.length > 0 && (
            <span className="text-[10px] text-gray-500">
              {p.conflicts.length} conflict{p.conflicts.length !== 1 ? "s" : ""} resolved
            </span>
          )}
        </div>
      );
    }

    case "approval_requested": {
      return (
        <div className="flex flex-col gap-1">
          <span className="text-amber-400 font-semibold">{p.action?.title || "Action requires approval"}</span>
          {p.action?.risk_level && (
            <span className={`text-[10px] px-1.5 py-0.5 rounded w-fit ${
              p.action.risk_level === "critical" ? "bg-red-900/60 text-red-400" :
              p.action.risk_level === "high" ? "bg-orange-900/60 text-orange-400" :
              "bg-yellow-900/60 text-yellow-400"
            }`}>Risk: {p.action.risk_level}</span>
          )}
          {p.action?.description && <span className="text-gray-400 text-[10px]">{p.action.description}</span>}
        </div>
      );
    }

    case "approval_response": {
      return (
        <span>
          Decision: <span className={p.decision === "approved" ? "text-emerald-400 font-semibold" : "text-red-400 font-semibold"}>{p.decision}</span>
          {p.note && <span className="text-gray-500"> — {p.note}</span>}
        </span>
      );
    }

    case "postmortem_ready": {
      return (
        <div className="flex flex-col gap-1">
          <span className="text-emerald-300 font-semibold">Postmortem report generated</span>
          {p.executive_summary && <span className="text-gray-400 text-[10px]">{p.executive_summary}</span>}
          {p.root_cause && <span className="text-gray-500 text-[10px]">Root cause: {p.root_cause}</span>}
        </div>
      );
    }

    case "incident_created": {
      const inc = p.incident || p;
      return (
        <span>
          Incident <span className="text-blue-400 font-semibold">{inc.id || "created"}</span>
          {inc.title && <span className="text-gray-300"> — {inc.title}</span>}
        </span>
      );
    }

    case "incident_resolved": {
      return <span className="text-emerald-400 font-semibold">Incident resolved ✓</span>;
    }

    case "memory_recalled": {
      const count = p.similar_incidents?.length || 0;
      return (
        <span>
          Found <span className="text-blue-400 font-semibold">{count}</span> similar past incident{count !== 1 ? "s" : ""}
        </span>
      );
    }

    case "timeline_updated": {
      return (
        <span>
          {p.agent && <span className="text-cyan-400 font-semibold">{p.agent.replace("_", " ")}: </span>}
          <span className="text-gray-300">{p.event}</span>
        </span>
      );
    }

    case "ping":
      return <span className="text-gray-600">keepalive</span>;

    default:
      // Fallback: show compact summary instead of raw JSON
      if (typeof p === "object" && p !== null) {
        const keys = Object.keys(p);
        return (
          <span className="text-gray-400">
            {keys.slice(0, 4).map(k => {
              const val = p[k];
              const display = typeof val === "string" ? val : typeof val === "number" ? val : "...";
              return `${k}: ${typeof display === "string" && display.length > 60 ? display.slice(0, 60) + "…" : display}`;
            }).join(" · ")}
            {keys.length > 4 && ` (+${keys.length - 4} more)`}
          </span>
        );
      }
      return <span className="text-gray-400">{String(p)}</span>;
  }
}

const eventLabels: Record<string, { label: string; color: string }> = {
  incident_state_sync: { label: "SYNC", color: "text-blue-400" },
  agent_status_change: { label: "AGENT", color: "text-cyan-400" },
  finding_added: { label: "FINDING", color: "text-violet-400" },
  evidence_added: { label: "EVIDENCE", color: "text-teal-400" },
  conflict_detected: { label: "CONFLICT", color: "text-red-400" },
  challenge_resolved: { label: "CHALLENGE", color: "text-purple-400" },
  consensus_reached: { label: "CONSENSUS", color: "text-emerald-400" },
  approval_requested: { label: "APPROVAL", color: "text-amber-400" },
  approval_response: { label: "DECISION", color: "text-amber-300" },
  postmortem_ready: { label: "POSTMORTEM", color: "text-emerald-300" },
  incident_created: { label: "CREATED", color: "text-blue-300" },
  incident_resolved: { label: "RESOLVED", color: "text-emerald-400" },
  memory_recalled: { label: "MEMORY", color: "text-indigo-400" },
  timeline_updated: { label: "TIMELINE", color: "text-gray-400" },
  ping: { label: "PING", color: "text-gray-600" },
};

export function EventStream({ events }: { events: SwarmEvent[] }) {
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [events]);

  return (
    <div className="flex flex-col h-full bg-black p-4 font-mono text-xs">
      <div className="flex items-center gap-2 mb-4">
        <div className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
        <h2 className="text-sm font-bold text-gray-400 uppercase tracking-wider">Live Event Stream</h2>
      </div>
      <div 
        ref={scrollRef}
        className="flex-1 overflow-y-auto space-y-2 pr-2 scrollbar-thin scrollbar-thumb-gray-800"
      >
        {events.map((ev, i) => {
          const meta = eventLabels[ev.event] || { label: ev.event, color: "text-gray-400" };
          return (
            <div key={i} className="text-gray-300 break-words border-b border-gray-900 pb-2">
              <div className="flex items-start gap-2">
                <span className="text-emerald-500 shrink-0">[{new Date().toLocaleTimeString()}]</span>
                <span className={`${meta.color} font-bold shrink-0 uppercase text-[10px] mt-0.5 px-1.5 py-0.5 rounded bg-gray-900 border border-gray-800`}>
                  {meta.label}
                </span>
                <div className="min-w-0 flex-1">
                  {formatEventPayload(ev)}
                </div>
              </div>
            </div>
          );
        })}
        {events.length === 0 && (
          <div className="text-gray-600 italic">Waiting for swarm events...</div>
        )}
      </div>
    </div>
  );
}
