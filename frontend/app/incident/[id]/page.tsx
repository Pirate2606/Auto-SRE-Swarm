"use client";

import { useSwarmSocket } from "../../../hooks/useSwarmSocket";
import { SwarmPanel } from "../../../components/SwarmPanel";
import { EventStream } from "../../../components/EventStream";
import { EvidenceGraph } from "../../../components/EvidenceGraph";
import { ConsensusView } from "../../../components/ConsensusView";
import { ConflictBanner } from "../../../components/ConflictBanner";
import { ApprovalDialog } from "../../../components/ApprovalDialog";
import { IncidentTimeline } from "../../../components/IncidentTimeline";
import { PostmortemModal } from "../../../components/PostmortemModal";
import { Activity, ShieldAlert, Wifi, WifiOff, FileText } from "lucide-react";
import { useState, useEffect } from "react";

export default function IncidentPage({ params }: { params: { id: string } }) {
  const { state, sendApprovalResponse } = useSwarmSocket(params.id);
  const [showPostmortem, setShowPostmortem] = useState(false);

  // Auto-show postmortem when it arrives
  useEffect(() => {
    if (state.postmortem) {
      setShowPostmortem(true);
    }
  }, [state.postmortem]);

  // Derive the active incident from state
  const incident = state.incident;

  return (
    <main className="min-h-screen bg-gray-950 text-gray-200 p-4 font-mono">
      {/* Header */}
      <header className="flex items-center justify-between pb-4 border-b border-gray-800 mb-4">
        <div className="flex items-center gap-3">
          <Activity className="text-blue-500 w-6 h-6" />
          <h1 className="text-xl font-bold text-gray-100">
            {incident ? incident.title : "Loading Incident..."}
          </h1>
          {incident && (
            <span className={`px-2 py-1 text-xs font-bold rounded ${
              incident.severity === "P1" ? "bg-red-900 text-red-300" :
              incident.severity === "P2" ? "bg-orange-900 text-orange-300" :
              "bg-gray-800 text-gray-300"
            }`}>
              {incident.severity}
            </span>
          )}
        </div>
        <div className="flex items-center gap-4">
          {/* Status Badge */}
          {incident && (
            <div className="flex items-center gap-2">
              <span className="text-sm text-gray-400">Status:</span>
              <span className="text-sm font-semibold text-blue-400 uppercase">
                {incident.status}
              </span>
            </div>
          )}
          {state.postmortem && (
            <button
              onClick={() => setShowPostmortem(true)}
              className="flex items-center gap-2 px-4 py-1.5 bg-blue-600 hover:bg-blue-500 text-white text-sm font-bold rounded-lg shadow-lg shadow-blue-900/20 transition-all"
            >
              <FileText className="w-4 h-4" /> View Postmortem
            </button>
          )}
          {/* Connection Status */}
          <div className="flex items-center gap-2 px-3 py-1 bg-gray-900 rounded-full border border-gray-800">
            {state.connectionStatus === "connected" ? (
              <Wifi className="w-4 h-4 text-emerald-500" />
            ) : state.connectionStatus === "connecting" ? (
              <Wifi className="w-4 h-4 text-yellow-500 animate-pulse" />
            ) : (
              <WifiOff className="w-4 h-4 text-red-500" />
            )}
            <span className="text-xs text-gray-400">{state.connectionStatus}</span>
          </div>
        </div>
      </header>

      {/* Main Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-4 h-[calc(100vh-100px)]">
        {/* Left Column: Swarm Status & Event Stream */}
        <div className="lg:col-span-3 flex flex-col gap-4 overflow-hidden">
          <div className="h-[40%] bg-gray-900 border border-gray-800 rounded-lg overflow-hidden">
            <SwarmPanel agentStatuses={state.agentStatuses} />
          </div>
          <div className="h-[60%] bg-gray-900 border border-gray-800 rounded-lg overflow-hidden">
            <EventStream events={state.events} />
          </div>
        </div>

        {/* Center/Right Column: Evidence Graph & Consensus */}
        <div className="lg:col-span-6 flex flex-col gap-4 overflow-hidden">
          {state.conflicts.length > 0 && (
            <ConflictBanner conflicts={state.conflicts} />
          )}
          
          <div className="flex-1 bg-gray-900 border border-gray-800 rounded-lg overflow-hidden relative">
            <EvidenceGraph
              nodes={state.evidenceNodes}
              findings={state.findings}
              consensus={state.consensus}
              conflicts={state.conflicts}
              postmortem={state.postmortem}
            />
          </div>
        </div>

        {/* Far Right Column: Timeline & Consensus Details */}
        <div className="lg:col-span-3 flex flex-col gap-4 overflow-hidden">
          <div className="h-[50%] bg-gray-900 border border-gray-800 rounded-lg overflow-hidden">
            <ConsensusView consensus={state.consensus} confidence={state.incident?.consensus_confidence} />
          </div>
          <div className="h-[50%] bg-gray-900 border border-gray-800 rounded-lg overflow-hidden">
            <IncidentTimeline timeline={state.timeline} />
          </div>
        </div>
      </div>

      {/* Modals */}
      {state.pendingApprovals.length > 0 && (
        <ApprovalDialog 
          approvals={state.pendingApprovals} 
          onDecision={(id, approved, note) => sendApprovalResponse(id, approved, note)} 
        />
      )}

      {showPostmortem && state.postmortem && (
        <PostmortemModal
          postmortem={state.postmortem}
          onClose={() => setShowPostmortem(false)}
        />
      )}
    </main>
  );
}
