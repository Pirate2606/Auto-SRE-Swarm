import { ApprovalRequest } from "../lib/types";
import { motion, AnimatePresence } from "framer-motion";
import { AlertOctagon, Check, X } from "lucide-react";
import { useState } from "react";

export function ApprovalDialog({
  approvals,
  onDecision,
}: {
  approvals: ApprovalRequest[];
  onDecision: (id: string, approved: boolean, note: string) => void;
}) {
  const [notes, setNotes] = useState<Record<string, string>>({});

  const pending = approvals.filter(a => a.decision === "pending");
  if (pending.length === 0) return null;

  return (
    <AnimatePresence>
      <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4">
        <motion.div
          initial={{ scale: 0.9, opacity: 0 }}
          animate={{ scale: 1, opacity: 1 }}
          exit={{ scale: 0.9, opacity: 0 }}
          className="bg-gray-900 border border-gray-700 rounded-xl shadow-2xl max-w-2xl w-full overflow-hidden"
        >
          <div className="bg-red-950/50 border-b border-red-900 p-4 flex items-center gap-3">
            <AlertOctagon className="w-6 h-6 text-red-500 animate-pulse" />
            <h2 className="text-xl font-bold text-red-100">Human Approval Required</h2>
          </div>
          
          <div className="p-6 space-y-6 max-h-[70vh] overflow-y-auto">
            {pending.map((req) => (
              <div key={req.id} className="bg-gray-950 border border-gray-800 rounded-lg p-5 space-y-4">
                <div>
                  <div className="flex items-center justify-between mb-2">
                    <h3 className="font-bold text-lg text-gray-200">{req.action.title}</h3>
                    <span className={`px-2 py-1 text-xs font-bold rounded ${
                      req.action.risk_level === "critical" ? "bg-red-900 text-red-300" :
                      req.action.risk_level === "high" ? "bg-orange-900 text-orange-300" :
                      "bg-yellow-900 text-yellow-300"
                    }`}>
                      {req.action.risk_level.toUpperCase()} RISK
                    </span>
                  </div>
                  <p className="text-sm text-gray-400">{req.action.description}</p>
                </div>

                <div className="grid grid-cols-2 gap-4 text-sm">
                  <div className="bg-gray-900 p-3 rounded border border-gray-800">
                    <span className="block text-xs font-bold text-gray-500 mb-1">Estimated Impact</span>
                    <span className="text-gray-300">{req.action.estimated_impact}</span>
                  </div>
                  <div className="bg-gray-900 p-3 rounded border border-gray-800">
                    <span className="block text-xs font-bold text-gray-500 mb-1">Rollback Plan</span>
                    <span className="text-gray-300">{req.action.rollback_plan}</span>
                  </div>
                </div>

                <div className="pt-2">
                  <textarea
                    className="w-full bg-gray-900 border border-gray-700 rounded-md p-3 text-sm text-gray-200 placeholder-gray-600 focus:outline-none focus:border-blue-500"
                    placeholder="Add an optional note or justification..."
                    value={notes[req.id] || ""}
                    onChange={(e) => setNotes({ ...notes, [req.id]: e.target.value })}
                    rows={2}
                  />
                </div>

                <div className="flex items-center justify-end gap-3 pt-2">
                  <button
                    onClick={() => onDecision(req.id, false, notes[req.id] || "")}
                    className="flex items-center gap-2 px-4 py-2 bg-gray-800 hover:bg-gray-700 text-gray-300 rounded-md transition-colors"
                  >
                    <X className="w-4 h-4" /> Reject
                  </button>
                  <button
                    onClick={() => onDecision(req.id, true, notes[req.id] || "")}
                    className="flex items-center gap-2 px-6 py-2 bg-emerald-600 hover:bg-emerald-500 text-white font-bold rounded-md shadow-lg shadow-emerald-900/50 transition-all hover:scale-105"
                  >
                    <Check className="w-4 h-4" /> Approve Action
                  </button>
                </div>
              </div>
            ))}
          </div>
        </motion.div>
      </div>
    </AnimatePresence>
  );
}
