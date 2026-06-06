import { ConsensusResult } from "../lib/types";
import { ConfidenceGauge } from "./ConfidenceGauge";
import { BrainCircuit } from "lucide-react";

export function ConsensusView({ consensus, confidence }: { consensus: ConsensusResult | null, confidence?: number | null }) {
  if (!consensus) {
    return (
      <div className="flex flex-col items-center justify-center h-full text-gray-500 p-6 text-center">
        <BrainCircuit className="w-12 h-12 mb-4 opacity-20" />
        <p>Swarm is currently investigating. Awaiting consensus formulation...</p>
      </div>
    );
  }

  const displayConf = confidence ?? consensus.confidence;

  return (
    <div className="flex flex-col h-full bg-gray-950 p-6 overflow-y-auto">
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-3">
          <BrainCircuit className="w-6 h-6 text-emerald-500" />
          <h2 className="text-lg font-bold text-gray-100 uppercase tracking-wider">Active Consensus</h2>
        </div>
        <ConfidenceGauge confidence={displayConf} />
      </div>

      <div className="space-y-4">
        <div>
          <h3 className="text-xs uppercase text-gray-500 font-bold mb-1">Synthesized Hypothesis</h3>
          <p className="text-lg text-emerald-400 font-bold">{consensus.hypothesis.title}</p>
        </div>
        
        <div className="bg-gray-900 p-4 rounded-lg border border-gray-800">
          <h3 className="text-xs uppercase text-gray-500 font-bold mb-2">Root Cause Analysis</h3>
          <p className="text-sm text-gray-300 leading-relaxed">
            {consensus.hypothesis.description}
          </p>
        </div>

        <div>
          <h3 className="text-xs uppercase text-gray-500 font-bold mb-2">Evidence Chain</h3>
          <div className="flex flex-wrap gap-2">
            {consensus.evidence_chain.map((id, i) => (
              <span key={i} className="px-2 py-1 bg-gray-800 border border-gray-700 rounded text-xs text-gray-400 font-mono">
                {id.split("-")[0]}
              </span>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
