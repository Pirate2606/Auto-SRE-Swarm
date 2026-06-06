import { AgentName, AgentStatus } from "../lib/types";
import { motion, AnimatePresence } from "framer-motion";
import { Bot, CheckCircle2, AlertCircle, Loader2 } from "lucide-react";

const agentDisplayNames: Record<string, string> = {
  commander: "Commander",
  log_forensics: "Log Forensics",
  telemetry_intel: "Telemetry Intel",
  deployment_intel: "Deployment Intel",
  consensus_engine: "Consensus Engine",
  postmortem_intel: "Postmortem Intel",
  safety_validator: "Safety Validator",
};

export function SwarmPanel({ agentStatuses }: { agentStatuses: Record<string, AgentStatus> }) {
  const getStatusIcon = (status: AgentStatus) => {
    switch (status) {
      case "idle":
        return <Bot className="w-4 h-4 text-gray-500" />;
      case "investigating":
      case "challenging":
        return <Loader2 className="w-4 h-4 text-blue-400 animate-spin" />;
      case "done":
        return <CheckCircle2 className="w-4 h-4 text-emerald-400" />;
      case "error":
        return <AlertCircle className="w-4 h-4 text-red-500" />;
      default:
        return <Bot className="w-4 h-4 text-gray-500" />;
    }
  };

  const getStatusColor = (status: AgentStatus) => {
    switch (status) {
      case "idle": return "border-gray-800 text-gray-400";
      case "investigating": return "border-blue-500/50 text-blue-300 bg-blue-900/20";
      case "challenging": return "border-orange-500/50 text-orange-300 bg-orange-900/20";
      case "done": return "border-emerald-500/50 text-emerald-300 bg-emerald-900/20";
      case "error": return "border-red-500/50 text-red-300 bg-red-900/20";
      default: return "border-gray-800";
    }
  };

  return (
    <div className="flex flex-col h-full bg-gray-950 p-4">
      <h2 className="text-sm font-bold text-gray-400 uppercase tracking-wider mb-4">Swarm Agents</h2>
      <div className="flex-1 overflow-y-auto pr-2 space-y-2">
        <AnimatePresence>
          {Object.entries(agentStatuses).map(([agent, status]) => (
            <motion.div
              key={agent}
              layout
              initial={{ opacity: 0, x: -20 }}
              animate={{ opacity: 1, x: 0 }}
              className={`flex items-center justify-between p-3 rounded-lg border transition-colors ${getStatusColor(status)}`}
            >
              <div className="flex items-center gap-3">
                {getStatusIcon(status)}
                <span className="text-sm font-semibold">{agentDisplayNames[agent] || agent}</span>
              </div>
              <span className="text-xs uppercase font-mono tracking-widest opacity-80">
                {status}
              </span>
            </motion.div>
          ))}
        </AnimatePresence>
      </div>
    </div>
  );
}
