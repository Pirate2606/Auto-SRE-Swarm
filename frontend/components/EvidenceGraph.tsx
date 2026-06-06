import { useEffect } from "react";
import {
  ReactFlow,
  MiniMap,
  Controls,
  Background,
  useNodesState,
  useEdgesState,
  Node,
  Edge,
  MarkerType,
  Position,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import dagre from "dagre";
import {
  EvidenceNode,
  AgentFinding,
  ConsensusResult,
  Postmortem,
  Conflict,
} from "../lib/types";

/* ─── dagre auto-layout ─── */
const layout = (nodes: Node[], edges: Edge[], dir = "TB") => {
  const g = new dagre.graphlib.Graph();
  g.setDefaultEdgeLabel(() => ({}));
  g.setGraph({ rankdir: dir, nodesep: 60, ranksep: 80, marginx: 40, marginy: 40 });

  const W = 280, H = 130;
  nodes.forEach((n) => g.setNode(n.id, { width: W, height: H }));
  edges.forEach((e) => g.setEdge(e.source, e.target));
  dagre.layout(g);

  nodes.forEach((n) => {
    const pos = g.node(n.id);
    n.targetPosition = Position.Top;
    n.sourcePosition = Position.Bottom;
    n.position = { x: pos.x - W / 2, y: pos.y - H / 2 };
  });
  return { nodes, edges };
};

/* ─── colour palettes per agent ─── */
const AGENT_COLORS: Record<string, { bg: string; border: string; text: string }> = {
  log_forensics:   { bg: "rgba(30,58,138,0.85)",  border: "#3b82f6", text: "#93c5fd" },
  telemetry_intel:  { bg: "rgba(6,78,59,0.85)",    border: "#10b981", text: "#6ee7b7" },
  deployment_intel: { bg: "rgba(88,28,135,0.85)",   border: "#a855f7", text: "#c4b5fd" },
  commander:        { bg: "rgba(120,113,108,0.85)", border: "#a8a29e", text: "#d6d3d1" },
  consensus_engine: { bg: "rgba(146,64,14,0.85)",   border: "#f59e0b", text: "#fcd34d" },
  safety_validator: { bg: "rgba(127,29,29,0.85)",   border: "#ef4444", text: "#fca5a5" },
  postmortem_intel:{ bg: "rgba(21,94,117,0.85)",   border: "#06b6d4", text: "#67e8f9" },
};
const DEFAULT_C = { bg: "#1f2937", border: "#4b5563", text: "#9ca3af" };
const agentColor = (a: string) => AGENT_COLORS[a] ?? DEFAULT_C;

/* ─── helper: build a node ─── */
function mkNode(
  id: string,
  kind: string,
  agent: string,
  label: string,
  detail: string,
  conf: number | null,
  round: number | null,
  extra?: { borderWidth?: string },
): Node {
  const c = kind === "conflict"
    ? { bg: "rgba(127,29,29,0.9)", border: "#ef4444", text: "#fca5a5" }
    : kind === "consensus"
      ? { bg: "rgba(146,64,14,0.9)", border: "#f59e0b", text: "#fcd34d" }
      : kind === "postmortem"
        ? { bg: "rgba(21,94,117,0.9)", border: "#06b6d4", text: "#67e8f9" }
        : agentColor(agent);

  const kindBadge: Record<string, { label: string; color: string }> = {
    evidence: { label: "EVIDENCE", color: "bg-blue-500/20 text-blue-300" },
    finding:  { label: "FINDING",  color: "bg-emerald-500/20 text-emerald-300" },
    conflict: { label: "CONFLICT", color: "bg-red-500/20 text-red-300" },
    consensus:{ label: "CONSENSUS",color: "bg-amber-500/20 text-amber-300" },
    postmortem:{ label:"POSTMORTEM",color: "bg-cyan-500/20 text-cyan-300" },
  };
  const badge = kindBadge[kind] ?? { label: kind.toUpperCase(), color: "bg-gray-500/20 text-gray-300" };

  return {
    id,
    position: { x: 0, y: 0 },
    data: {
      label: (
        <div style={{ display: "flex", flexDirection: "column", gap: 4, padding: 10, height: "100%", overflow: "hidden", textAlign: "left" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexShrink: 0 }}>
            <span style={{ fontSize: 10, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.05em", color: c.text }}>
              {agent.replace(/_/g, " ")}
            </span>
            <span className={badge.color} style={{ fontSize: 9, padding: "2px 6px", borderRadius: 4, fontWeight: 700 }}>
              {badge.label}
            </span>
          </div>
          <span style={{ fontWeight: 600, fontSize: 11, color: "#f3f4f6", flex: 1, overflow: "hidden", textOverflow: "ellipsis", display: "-webkit-box", WebkitLineClamp: 3, WebkitBoxOrient: "vertical", wordBreak: "break-word" }}>
            {label}
          </span>
          <div style={{ display: "flex", justifyContent: "space-between", borderTop: "1px solid rgba(255,255,255,0.1)", paddingTop: 4, flexShrink: 0, fontSize: 10, color: "#9ca3af", fontFamily: "monospace" }}>
            {round != null && <span>Round {round}</span>}
            {conf != null && <span>Conf: {Math.round(conf * 100)}%</span>}
            {conf == null && round == null && <span>{detail}</span>}
          </div>
        </div>
      ),
    },
    className: "!p-0 rounded-lg border shadow-xl",
    style: {
      width: 280,
      height: 130,
      backgroundColor: c.bg,
      borderColor: c.border,
      borderWidth: extra?.borderWidth ?? "1px",
    },
  };
}

/* ─── helper: build an edge ─── */
function mkEdge(src: string, tgt: string, color = "#6b7280", animated = true, label?: string): Edge {
  return {
    id: `e-${src}-${tgt}`,
    source: src,
    target: tgt,
    animated,
    label,
    labelStyle: label ? { fill: "#9ca3af", fontSize: 9, fontWeight: 600 } : undefined,
    labelBgStyle: label ? { fill: "#111827", fillOpacity: 0.9 } : undefined,
    labelBgPadding: label ? [6, 3] as [number, number] : undefined,
    style: { stroke: color, strokeWidth: 2 },
    markerEnd: { type: MarkerType.ArrowClosed, color, width: 14, height: 14 },
  };
}

/* ─── component props ─── */
interface EvidenceGraphProps {
  nodes: EvidenceNode[];
  findings: AgentFinding[];
  consensus: ConsensusResult | null;
  conflicts: Conflict[];
  postmortem: Postmortem | null;
}

export function EvidenceGraph({ nodes: evidenceNodes, findings, consensus, conflicts, postmortem }: EvidenceGraphProps) {
  const [nodes, setNodes, onNodesChange] = useNodesState([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState([]);

  useEffect(() => {
    const allNodes: Node[] = [];
    const allEdges: Edge[] = [];
    const existingIds = new Set<string>();

    /* 1 ── Evidence nodes (raw agent output) ── */
    evidenceNodes.forEach((en) => {
      existingIds.add(en.id);
      allNodes.push(
        mkNode(en.id, "evidence", en.agent, en.summary, en.evidence_type, en.confidence, en.round_number),
      );
      en.parent_ids.forEach((pid) => {
        if (evidenceNodes.some((n) => n.id === pid)) {
          allEdges.push(mkEdge(pid, en.id, agentColor(en.agent).border));
        }
      });
    });

    /* 2 ── Agent findings ── */
    (findings || []).forEach((f) => {
      const fId = `finding-${f.id}`;
      if (existingIds.has(fId)) return;
      existingIds.add(fId);
      allNodes.push(
        mkNode(fId, "finding", f.agent, f.root_cause_hypothesis || f.summary, "", f.confidence, f.round_number),
      );
      // Connect finding to its supporting evidence
      (f.supporting_evidence || []).forEach((eid) => {
        if (existingIds.has(eid)) {
          allEdges.push(mkEdge(eid, fId, "#10b981"));
        }
      });
      // If no supporting evidence links exist, connect to same-agent evidence
      if (!f.supporting_evidence || f.supporting_evidence.length === 0) {
        const agentEvidence = evidenceNodes.filter((en) => en.agent === f.agent);
        agentEvidence.forEach((en) => {
          allEdges.push(mkEdge(en.id, fId, "#10b981"));
        });
      }
    });

    /* 3 ── Conflicts ── */
    (conflicts || []).forEach((c, idx) => {
      const cId = `conflict-${c.id || idx}`;
      if (existingIds.has(cId)) return;
      existingIds.add(cId);
      const summary = `${(c.agent_a || "").replace(/_/g, " ")} vs ${(c.agent_b || "").replace(/_/g, " ")}`;
      allNodes.push(
        mkNode(cId, "conflict", "conflict", summary, c.resolved ? "Resolved" : "Unresolved", null, null, { borderWidth: "2px" }),
      );
      // Connect to evidence from conflicting agents
      (c.evidence_ids || []).forEach((eid) => {
        if (existingIds.has(eid)) {
          allEdges.push(mkEdge(eid, cId, "#ef4444"));
        }
      });
      // Fallback: connect to agent evidence
      if (!c.evidence_ids || c.evidence_ids.length === 0) {
        const agentAEvidence = evidenceNodes.filter((en) => en.agent === c.agent_a);
        const agentBEvidence = evidenceNodes.filter((en) => en.agent === c.agent_b);
        agentAEvidence.forEach((en) => allEdges.push(mkEdge(en.id, cId, "#ef4444")));
        agentBEvidence.forEach((en) => allEdges.push(mkEdge(en.id, cId, "#ef4444")));
      }
    });

    /* 4 ── Consensus ── */
    if (consensus) {
      const consId = "consensus-result";
      if (!existingIds.has(consId)) {
        existingIds.add(consId);
        const h = consensus.hypothesis;
        allNodes.push(
          mkNode(consId, "consensus", "consensus_engine", h?.title || "Consensus Reached", h?.description || "", consensus.confidence, consensus.round_number),
        );
        // Connect findings to consensus
        const findingNodeIds = allNodes.filter((n) => n.id.startsWith("finding-")).map((n) => n.id);
        if (findingNodeIds.length > 0) {
          findingNodeIds.forEach((fId) => allEdges.push(mkEdge(fId, consId, "#f59e0b")));
        } else {
          // Connect evidence directly to consensus if no findings
          evidenceNodes.forEach((en) => allEdges.push(mkEdge(en.id, consId, "#f59e0b")));
        }
        // Connect conflicts to consensus
        const conflictNodeIds = allNodes.filter((n) => n.id.startsWith("conflict-")).map((n) => n.id);
        conflictNodeIds.forEach((cId) => allEdges.push(mkEdge(cId, consId, "#f59e0b", true, "resolved")));
      }
    }

    /* 5 ── Postmortem ── */
    if (postmortem) {
      const pmId = "postmortem-report";
      if (!existingIds.has(pmId)) {
        existingIds.add(pmId);
        const riskPct = postmortem.recurrence_risk != null ? Math.round(postmortem.recurrence_risk * 100) : null;
        allNodes.push(
          mkNode(pmId, "postmortem", "postmortem_intel",
            "Postmortem Report",
            `${(postmortem.remediation_actions || []).length} remediations`,
            riskPct != null ? riskPct / 100 : null,
            null,
          ),
        );
        // Connect consensus → postmortem
        if (existingIds.has("consensus-result")) {
          allEdges.push(mkEdge("consensus-result", pmId, "#06b6d4"));
        } else {
          // Connect evidence directly if no consensus
          evidenceNodes.forEach((en) => allEdges.push(mkEdge(en.id, pmId, "#06b6d4")));
        }
      }
    }

    /* 6 ── If only evidence and nothing else, connect them to an incident root ── */
    if (allNodes.length > 0 && allNodes.every((n) => !n.id.startsWith("finding-") && !n.id.startsWith("conflict-") && n.id !== "consensus-result" && n.id !== "postmortem-report")) {
      // Add an incident root node to connect orphan evidence
      const rootId = "incident-root";
      allNodes.unshift(
        mkNode(rootId, "evidence", "commander", "Incident Dispatched", "Investigation started", null, 0),
      );
      existingIds.add(rootId);
      evidenceNodes.forEach((en) => {
        if (en.parent_ids.length === 0) {
          allEdges.push(mkEdge(rootId, en.id, agentColor(en.agent).border));
        }
      });
    }

    // Even for evidence-only graphs, ensure orphan evidence nodes connect to something if parent_ids are empty
    if (allNodes.length > 1) {
      const hasIncoming = new Set(allEdges.map(e => e.target));
      allNodes.forEach(n => {
        if (n.id !== "incident-root" && !hasIncoming.has(n.id)) {
          // This node has no incoming edges — connect from incident-root if it exists, or skip
          if (existingIds.has("incident-root")) {
            allEdges.push(mkEdge("incident-root", n.id, "#4b5563"));
          }
        }
      });
    }

    const { nodes: ln, edges: le } = layout(allNodes, allEdges);
    setNodes([...ln]);
    setEdges([...le]);
  }, [evidenceNodes, findings, consensus, conflicts, postmortem, setNodes, setEdges]);

  return (
    <div className="w-full h-full bg-gray-950 relative">
      <div className="absolute top-4 left-4 z-10 bg-gray-900/90 px-4 py-1.5 rounded-full border border-gray-700 text-xs font-bold text-gray-300 uppercase tracking-widest shadow-md backdrop-blur-sm">
        Investigation DAG
      </div>
      {/* Legend */}
      <div className="absolute top-4 right-4 z-10 flex flex-wrap gap-2">
        {[
          { label: "Evidence", color: "#3b82f6" },
          { label: "Finding", color: "#10b981" },
          { label: "Conflict", color: "#ef4444" },
          { label: "Consensus", color: "#f59e0b" },
          { label: "Postmortem", color: "#06b6d4" },
        ].map(({ label, color }) => (
          <div key={label} className="flex items-center gap-1.5 bg-gray-900/80 px-2.5 py-1 rounded-full border border-gray-800 backdrop-blur-sm">
            <div style={{ width: 8, height: 8, borderRadius: "50%", backgroundColor: color }} />
            <span className="text-[10px] text-gray-400 font-medium">{label}</span>
          </div>
        ))}
      </div>
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        fitView
        fitViewOptions={{ padding: 0.3 }}
        className="bg-gray-950"
        minZoom={0.1}
        maxZoom={1.5}
        proOptions={{ hideAttribution: true }}
      >
        <Background color="#374151" gap={20} size={1} />
        <Controls className="bg-gray-900 fill-gray-400" />
        <MiniMap
          zoomable
          pannable
          nodeColor="#4b5563"
          maskColor="rgba(0, 0, 0, 0.6)"
          className="bg-gray-900 rounded-lg border border-gray-800"
        />
      </ReactFlow>
    </div>
  );
}
