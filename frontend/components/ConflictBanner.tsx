import { Conflict } from "../lib/types";
import { motion, AnimatePresence } from "framer-motion";
import { ShieldAlert, X, Swords } from "lucide-react";
import { useState } from "react";

export function ConflictBanner({ conflicts }: { conflicts: Conflict[] }) {
  const [dismissed, setDismissed] = useState(false);

  if (conflicts.length === 0 || dismissed) return null;

  // Only show unresolved conflicts prominently
  const unresolved = conflicts.filter((c) => !c.resolved);
  const resolvedCount = conflicts.length - unresolved.length;
  const displayConflicts = unresolved.length > 0 ? unresolved : conflicts;

  return (
    <AnimatePresence>
      <motion.div
        initial={{ opacity: 0, height: 0 }}
        animate={{ opacity: 1, height: "auto" }}
        exit={{ opacity: 0, height: 0 }}
        className="w-full shrink-0 bg-gradient-to-r from-orange-950/60 via-orange-950/40 to-orange-950/60 border border-orange-500/30 backdrop-blur-sm rounded-lg shadow-lg overflow-hidden"
      >
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-orange-900/40">
          <div className="flex items-center gap-2.5">
            <div className="p-1.5 bg-orange-500/15 rounded-lg">
              <ShieldAlert className="w-4 h-4 text-orange-400" />
            </div>
            <div>
              <h3 className="text-sm font-bold text-orange-300">
                Agent Conflict{displayConflicts.length > 1 ? "s" : ""} Detected
              </h3>
              <p className="text-[10px] text-orange-400/70 mt-0.5">
                {unresolved.length > 0
                  ? "Commander is initiating a challenge round to resolve discrepancies..."
                  : `All ${resolvedCount} conflict${resolvedCount > 1 ? "s" : ""} resolved`}
              </p>
            </div>
          </div>
          <button
            onClick={() => setDismissed(true)}
            className="p-1.5 text-orange-400/60 hover:text-orange-300 hover:bg-orange-900/30 rounded-lg transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Conflict Cards */}
        <div className="p-3 space-y-2 max-h-48 overflow-y-auto custom-scrollbar">
          {displayConflicts.map((c, i) => (
            <div
              key={c.id || i}
              className={`rounded-lg border p-3 transition-colors ${
                c.resolved
                  ? "bg-gray-900/50 border-gray-700/50"
                  : "bg-orange-950/30 border-orange-800/40"
              }`}
            >
              <div className="flex items-center gap-3">
                {/* Agent A */}
                <div className="flex-1 min-w-0">
                  <span className="text-[10px] font-bold text-gray-400 uppercase tracking-wider block mb-1">
                    {(c.agent_a || "").replace(/_/g, " ")}
                  </span>
                  <p className="text-xs text-orange-200/90 leading-relaxed line-clamp-2">
                    {c.position_a}
                  </p>
                </div>

                {/* VS divider */}
                <div className="flex flex-col items-center shrink-0 px-1">
                  <Swords className={`w-4 h-4 ${c.resolved ? "text-gray-600" : "text-orange-500"}`} />
                  <span className="text-[8px] font-bold text-gray-600 uppercase mt-0.5">vs</span>
                </div>

                {/* Agent B */}
                <div className="flex-1 min-w-0">
                  <span className="text-[10px] font-bold text-gray-400 uppercase tracking-wider block mb-1">
                    {(c.agent_b || "").replace(/_/g, " ")}
                  </span>
                  <p className="text-xs text-orange-200/90 leading-relaxed line-clamp-2">
                    {c.position_b}
                  </p>
                </div>

                {/* Status badge */}
                <span
                  className={`text-[9px] font-bold px-2 py-1 rounded-full shrink-0 ${
                    c.resolved
                      ? "bg-emerald-500/10 text-emerald-400 border border-emerald-500/20"
                      : "bg-orange-500/10 text-orange-400 border border-orange-500/20 animate-pulse"
                  }`}
                >
                  {c.resolved ? "Resolved" : "Active"}
                </span>
              </div>
            </div>
          ))}
        </div>
      </motion.div>
    </AnimatePresence>
  );
}
