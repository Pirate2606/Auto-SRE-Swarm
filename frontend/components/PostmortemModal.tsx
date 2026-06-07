import { Postmortem } from "../lib/types";
import { motion, AnimatePresence } from "framer-motion";
import {
  FileText,
  X,
  AlertTriangle,
  ShieldCheck,
  Activity,
  CheckCircle2,
  ChevronRight,
  Clock,
  Target,
  TrendingUp,
  Wrench,
  Lightbulb,
} from "lucide-react";
import { useState } from "react";

type Tab = "summary" | "timeline" | "remediation";

export function PostmortemModal({
  postmortem,
  onClose,
}: {
  postmortem: Postmortem;
  onClose: () => void;
}) {
  const [activeTab, setActiveTab] = useState<Tab>("summary");

  const riskPct = Math.round((postmortem.recurrence_risk ?? 0) * 100);
  const riskLevel =
    riskPct > 70 ? { label: "Critical", color: "red" } :
    riskPct > 40 ? { label: "Elevated", color: "yellow" } :
    { label: "Low", color: "emerald" };

  const tabMeta: { key: Tab; label: string; icon: React.ReactNode }[] = [
    { key: "summary",     label: "Executive Summary", icon: <Activity className="w-4 h-4" /> },
    { key: "timeline",    label: "Timeline",          icon: <Clock className="w-4 h-4" /> },
    { key: "remediation", label: "Remediation",       icon: <Wrench className="w-4 h-4" /> },
  ];

  return (
    <AnimatePresence>
      <div
        className="fixed inset-0 z-[100] flex items-center justify-center bg-black/70 backdrop-blur-sm p-4 sm:p-6"
        onClick={onClose}
      >
        <motion.div
          initial={{ scale: 0.95, opacity: 0, y: 20 }}
          animate={{ scale: 1, opacity: 1, y: 0 }}
          exit={{ scale: 0.95, opacity: 0, y: 20 }}
          transition={{ type: "spring", duration: 0.5, bounce: 0.15 }}
          onClick={(e) => e.stopPropagation()}
          className="bg-gray-950 border border-gray-800 rounded-2xl shadow-2xl shadow-black/60 flex flex-col w-full max-w-5xl max-h-[90vh] overflow-hidden"
        >
          {/* ─── Header ─── */}
          <div className="flex items-center justify-between px-6 py-5 border-b border-gray-800 bg-gradient-to-r from-gray-900 via-gray-900 to-gray-950">
            <div className="flex items-center gap-4">
              <div className="p-3 bg-gradient-to-br from-blue-500/15 to-cyan-500/10 rounded-xl border border-blue-500/20">
                <FileText className="w-7 h-7 text-blue-400" />
              </div>
              <div>
                <h2 className="text-xl sm:text-2xl font-bold text-gray-100 tracking-tight">
                  Incident Postmortem
                </h2>
                <div className="flex items-center gap-3 mt-1 text-xs text-gray-500">
                  <span className="font-mono bg-gray-800 px-2 py-0.5 rounded">
                    {postmortem.incident_id}
                  </span>
                  <span className="hidden sm:inline">•</span>
                  <span className="hidden sm:inline">
                    {new Date(postmortem.generated_at).toLocaleString()}
                  </span>
                </div>
              </div>
            </div>
            <button
              onClick={onClose}
              className="p-2 text-gray-500 hover:text-gray-100 hover:bg-gray-800 rounded-lg transition-colors"
            >
              <X className="w-5 h-5" />
            </button>
          </div>

          {/* ─── Tabs ─── */}
          <div className="flex border-b border-gray-800 bg-gray-900/50 px-4 sm:px-6 gap-1">
            {tabMeta.map(({ key, label, icon }) => (
              <button
                key={key}
                onClick={() => setActiveTab(key)}
                className={`flex items-center gap-2 px-4 sm:px-5 py-3.5 text-xs sm:text-sm font-semibold transition-all border-b-2 rounded-t-lg ${
                  activeTab === key
                    ? "border-blue-500 text-blue-400 bg-blue-500/5"
                    : "border-transparent text-gray-500 hover:text-gray-300 hover:bg-gray-800/50"
                }`}
              >
                {icon}
                <span className="hidden sm:inline">{label}</span>
                <span className="sm:hidden">{key === "summary" ? "Summary" : label}</span>
              </button>
            ))}
          </div>

          {/* ─── Content ─── */}
          <div className="flex-1 overflow-y-auto p-5 sm:p-6 custom-scrollbar">
            {/* SUMMARY TAB */}
            {activeTab === "summary" && (
              <motion.div
                initial={{ opacity: 0, x: -10 }}
                animate={{ opacity: 1, x: 0 }}
                className="space-y-6"
              >
                {/* Executive Summary */}
                <section>
                  <SectionHeader icon={<Activity className="w-5 h-5 text-purple-400" />} title="Executive Summary" />
                  <div className="bg-gray-900/80 border border-gray-800 rounded-xl p-5 text-gray-300 leading-relaxed text-sm">
                    {postmortem.executive_summary}
                  </div>
                </section>

                {/* Root Cause + Risk side by side */}
                <div className="grid grid-cols-1 md:grid-cols-3 gap-5">
                  <section className="md:col-span-2">
                    <SectionHeader icon={<Target className="w-5 h-5 text-orange-400" />} title="Root Cause" />
                    <div className="h-full bg-gradient-to-br from-orange-500/5 to-transparent border border-orange-500/20 rounded-xl p-5 text-orange-200/90 text-sm leading-relaxed">
                      {postmortem.root_cause}
                    </div>
                  </section>

                  <section>
                    <SectionHeader icon={<TrendingUp className="w-5 h-5 text-emerald-400" />} title="Recurrence Risk" />
                    <div className={`h-full border rounded-xl p-5 flex flex-col items-center justify-center gap-3
                      ${riskLevel.color === "red" ? "bg-red-500/5 border-red-500/20" :
                        riskLevel.color === "yellow" ? "bg-yellow-500/5 border-yellow-500/20" :
                        "bg-emerald-500/5 border-emerald-500/20"}`}
                    >
                      <div className={`text-5xl font-black tracking-tighter
                        ${riskLevel.color === "red" ? "text-red-400" :
                          riskLevel.color === "yellow" ? "text-yellow-400" :
                          "text-emerald-400"}`}
                      >
                        {riskPct}%
                      </div>
                      <span className={`text-[10px] font-bold uppercase tracking-widest px-3 py-1 rounded-full
                        ${riskLevel.color === "red" ? "bg-red-500/10 text-red-400" :
                          riskLevel.color === "yellow" ? "bg-yellow-500/10 text-yellow-400" :
                          "bg-emerald-500/10 text-emerald-400"}`}
                      >
                        {riskLevel.label} Risk
                      </span>
                    </div>
                  </section>
                </div>

                {/* Contributing Factors */}
                {(postmortem.contributing_factors || []).length > 0 && (
                  <section>
                    <SectionHeader icon={<AlertTriangle className="w-5 h-5 text-amber-400" />} title="Contributing Factors" />
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                      {(postmortem.contributing_factors || []).map((factor, idx, arr) => (
                        <div
                          key={idx}
                          className={`bg-gray-900/60 border border-gray-800 rounded-lg p-4 flex gap-3 text-sm text-gray-300 items-start hover:border-gray-700 transition-colors${
                            arr.length % 2 === 1 && idx === arr.length - 1 ? " sm:col-span-2" : ""
                          }`}
                        >
                          <div className="mt-0.5 shrink-0 w-5 h-5 rounded-full bg-amber-500/10 border border-amber-500/20 flex items-center justify-center">
                            <span className="text-[10px] font-bold text-amber-400">{idx + 1}</span>
                          </div>
                          <span className="leading-relaxed">{factor}</span>
                        </div>
                      ))}
                    </div>
                  </section>
                )}
              </motion.div>
            )}

            {/* TIMELINE TAB */}
            {activeTab === "timeline" && (
              <motion.div
                initial={{ opacity: 0, x: -10 }}
                animate={{ opacity: 1, x: 0 }}
                className="space-y-1"
              >
                {(postmortem.timeline || []).length === 0 ? (
                  <div className="text-center text-gray-500 py-12 text-sm">
                    No timeline entries available.
                  </div>
                ) : (
                  <div className="relative pl-8">
                    {/* Vertical line */}
                    <div className="absolute left-3 top-2 bottom-2 w-px bg-gradient-to-b from-blue-500/40 via-gray-700 to-gray-800" />

                    {(postmortem.timeline || []).map((entry, idx) => (
                      <div key={idx} className="relative pb-5 last:pb-0">
                        {/* Dot */}
                        <div className="absolute -left-5 top-1 w-3 h-3 rounded-full border-2 border-gray-950 bg-blue-500 shadow-[0_0_8px_rgba(59,130,246,0.4)]" />

                        <div className="bg-gray-900/60 border border-gray-800 rounded-lg p-4 hover:border-gray-700 transition-colors">
                          <div className="flex items-center justify-between mb-2">
                            <span className="text-[11px] font-bold text-blue-400 font-mono">
                              {new Date(entry.timestamp).toLocaleTimeString([], {
                                hour: "2-digit",
                                minute: "2-digit",
                                second: "2-digit",
                              })}
                            </span>
                            {entry.agent && (
                              <span className="text-[10px] bg-gray-800 text-gray-400 px-2.5 py-0.5 rounded-full font-mono border border-gray-700">
                                {entry.agent.replace(/_/g, " ")}
                              </span>
                            )}
                          </div>
                          <p className="text-sm text-gray-300 leading-relaxed">{entry.event}</p>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </motion.div>
            )}

            {/* REMEDIATION TAB */}
            {activeTab === "remediation" && (
              <motion.div
                initial={{ opacity: 0, x: -10 }}
                animate={{ opacity: 1, x: 0 }}
                className="space-y-8"
              >
                {/* Remediation Actions */}
                <section>
                  <SectionHeader icon={<Wrench className="w-5 h-5 text-blue-400" />} title="Remediation Actions" />
                  {(postmortem.remediation_actions || []).length === 0 ? (
                    <div className="text-center text-gray-500 py-8 text-sm">No actions recorded.</div>
                  ) : (
                    <div className="space-y-3">
                      {(postmortem.remediation_actions || []).map((action, idx) => (
                        <div
                          key={idx}
                          className="bg-gray-900/60 border border-gray-800 rounded-xl p-5 hover:border-gray-700 transition-colors"
                        >
                          <div className="flex flex-col sm:flex-row sm:items-start justify-between gap-3">
                            <div className="flex-1 min-w-0">
                              <p className="font-semibold text-gray-200 text-sm mb-2">{action.action}</p>
                              <div className="flex flex-wrap items-center gap-x-5 gap-y-1 text-xs text-gray-500">
                                <span>
                                  Owner:{" "}
                                  <span className="text-gray-300 font-medium">{action.owner}</span>
                                </span>
                                <span>
                                  Effort:{" "}
                                  <span className="text-gray-300 font-medium">{action.estimated_effort}</span>
                                </span>
                              </div>
                            </div>
                            <PriorityBadge priority={action.priority} />
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </section>

                {/* Prevention Recommendations */}
                {(postmortem.prevention_recommendations || []).length > 0 && (
                  <section>
                    <SectionHeader icon={<Lightbulb className="w-5 h-5 text-emerald-400" />} title="Prevention Recommendations" />
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                      {(postmortem.prevention_recommendations || []).map((rec, idx) => (
                        <div
                          key={idx}
                          className="bg-gradient-to-br from-emerald-500/5 to-transparent border border-emerald-500/15 rounded-xl p-5 flex gap-3 text-sm text-gray-300 items-start hover:border-emerald-500/30 transition-colors"
                        >
                          <CheckCircle2 className="w-4 h-4 text-emerald-500 shrink-0 mt-0.5" />
                          <span className="leading-relaxed">{rec}</span>
                        </div>
                      ))}
                    </div>
                  </section>
                )}
              </motion.div>
            )}
          </div>
        </motion.div>
      </div>
    </AnimatePresence>
  );
}

/* ─── Reusable sub-components ─── */

function SectionHeader({ icon, title }: { icon: React.ReactNode; title: string }) {
  return (
    <h3 className="text-sm font-semibold text-gray-300 flex items-center gap-2 mb-3 uppercase tracking-wider">
      {icon} {title}
    </h3>
  );
}

function PriorityBadge({ priority }: { priority: string }) {
  const p = (priority || "").toLowerCase();
  const style =
    p === "high" || p === "critical"
      ? "bg-red-500/10 text-red-400 border-red-500/20"
      : p === "medium"
        ? "bg-yellow-500/10 text-yellow-400 border-yellow-500/20"
        : "bg-blue-500/10 text-blue-400 border-blue-500/20";

  return (
    <span className={`px-3 py-1 rounded-full text-[10px] font-bold uppercase tracking-wider border shrink-0 ${style}`}>
      {priority}
    </span>
  );
}
