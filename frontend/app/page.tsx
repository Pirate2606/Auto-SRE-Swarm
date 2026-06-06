"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { api } from "../lib/api";
import { motion } from "framer-motion";
import { AlertTriangle, Terminal, Activity, Clock, ChevronRight } from "lucide-react";
import { IncidentSummary } from "../lib/types";

export default function Home() {
  const router = useRouter();
  const [loading, setLoading] = useState(false);
  const [loadingIncidents, setLoadingIncidents] = useState(true);
  const [recentIncidents, setRecentIncidents] = useState<IncidentSummary[]>([]);

  const [formData, setFormData] = useState({
    title: "High Latency in Payment Gateway",
    description: "Multiple users are reporting timeouts and high latency when attempting to checkout. Payment processing times have spiked beyond 5 seconds.",
    severity: "P1",
    source: "Manual Report",
    metadataStr: '{"region": "us-east-1", "service": "payment-api"}'
  });

  useEffect(() => {
    // Fetch recent incidents on load
    setLoadingIncidents(true);
    api.incidents.list(0, 6)
      .then((data) => setRecentIncidents(data))
      .catch((err) => console.error("Failed to load recent incidents:", err))
      .finally(() => setLoadingIncidents(false));
  }, []);

  const handleSimulateOutage = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    try {
      let metadata = {};
      try {
        metadata = JSON.parse(formData.metadataStr);
      } catch (e) {
        console.warn("Invalid metadata JSON, sending empty object");
      }

      const res = await api.incidents.create({
        title: formData.title,
        description: formData.description,
        severity: formData.severity as any,
        source: formData.source,
        metadata: metadata
      });
      router.push(`/incident/${res.id}`);
    } catch (err) {
      console.error(err);
      alert("Failed to simulate incident.");
      setLoading(false);
    }
  };

  return (
    <main className="min-h-screen flex flex-col items-center py-12 px-4 sm:px-6 lg:px-8 bg-gray-950 text-gray-100 relative overflow-x-hidden">
      {/* Background decoration */}
      <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_center,_var(--tw-gradient-stops))] from-blue-900/10 via-gray-950 to-gray-950 pointer-events-none" />

      <motion.div 
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.8 }}
        className="z-10 flex flex-col items-center w-full max-w-6xl text-center space-y-8"
      >
        <div className="flex items-center justify-center w-20 h-20 bg-blue-900/30 rounded-2xl border border-blue-500/30 shadow-[0_0_30px_rgba(59,130,246,0.3)]">
          <Activity className="w-10 h-10 text-blue-400" />
        </div>

        <h1 className="text-4xl sm:text-5xl lg:text-6xl font-extrabold tracking-tight text-transparent bg-clip-text bg-gradient-to-r from-blue-400 to-emerald-400">
          Auto-SRE Swarm
        </h1>
        
        <p className="text-base sm:text-lg text-gray-400 max-w-2xl">
          Autonomous, multi-agent incident response. AI agents collaborate in real-time to investigate logs, analyze telemetry, and synthesize root cause hypotheses.
        </p>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-8 w-full pt-8 text-left">
          {/* Form Column */}
          <div className="w-full">
            <h2 className="text-xl font-semibold mb-4 text-gray-300 flex items-center gap-2">
              <AlertTriangle className="w-5 h-5 text-red-400" />
              Trigger Incident
            </h2>
            <form onSubmit={handleSimulateOutage} className="bg-gray-900/50 p-6 sm:p-8 rounded-2xl border border-gray-800 space-y-5 shadow-xl backdrop-blur-sm">
              <div>
                <label className="block text-sm font-medium text-gray-400 mb-1">Incident Title</label>
                <input 
                  type="text" 
                  required
                  value={formData.title}
                  onChange={e => setFormData({...formData, title: e.target.value})}
                  className="w-full bg-gray-950 border border-gray-800 rounded-lg px-4 py-2.5 text-gray-100 focus:outline-none focus:border-blue-500 transition-colors"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-400 mb-1">Description</label>
                <textarea 
                  required
                  rows={4}
                  value={formData.description}
                  onChange={e => setFormData({...formData, description: e.target.value})}
                  className="w-full bg-gray-950 border border-gray-800 rounded-lg px-4 py-2.5 text-gray-100 focus:outline-none focus:border-blue-500 transition-colors resize-none"
                />
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-5">
                <div>
                  <label className="block text-sm font-medium text-gray-400 mb-1">Severity</label>
                  <select 
                    value={formData.severity}
                    onChange={e => setFormData({...formData, severity: e.target.value})}
                    className="w-full bg-gray-950 border border-gray-800 rounded-lg px-4 py-2.5 text-gray-100 focus:outline-none focus:border-blue-500 transition-colors"
                  >
                    <option value="P1">P1 (Critical)</option>
                    <option value="P2">P2 (High)</option>
                    <option value="P3">P3 (Medium)</option>
                    <option value="P4">P4 (Low)</option>
                  </select>
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-400 mb-1">Source</label>
                  <input 
                    type="text" 
                    value={formData.source}
                    onChange={e => setFormData({...formData, source: e.target.value})}
                    className="w-full bg-gray-950 border border-gray-800 rounded-lg px-4 py-2.5 text-gray-100 focus:outline-none focus:border-blue-500 transition-colors"
                  />
                </div>
              </div>
              
              <div className="pt-2">
                <motion.button
                  type="submit"
                  whileHover={{ scale: 1.01 }}
                  whileTap={{ scale: 0.98 }}
                  disabled={loading}
                  className="w-full flex items-center justify-center gap-3 px-6 py-3.5 bg-red-600/90 hover:bg-red-500 text-white font-bold rounded-xl shadow-[0_0_20px_rgba(220,38,38,0.25)] transition-all disabled:opacity-50"
                >
                  {loading ? (
                    <Terminal className="w-5 h-5 animate-spin" />
                  ) : (
                    <AlertTriangle className="w-5 h-5 group-hover:animate-pulse" />
                  )}
                  {loading ? "Dispatching Swarm..." : "Trigger Custom Incident"}
                </motion.button>
              </div>
            </form>
          </div>

          {/* Recent Incidents Column */}
          <div className="w-full flex flex-col">
            <h2 className="text-xl font-semibold mb-4 text-gray-300 flex items-center gap-2">
              <Clock className="w-5 h-5 text-blue-400" />
              Recent Incidents
            </h2>
            <div className="bg-gray-900/50 p-2 sm:p-4 rounded-2xl border border-gray-800 shadow-xl backdrop-blur-sm flex-1">
              {loadingIncidents ? (
                <div className="flex flex-col gap-2">
                  {[...Array(4)].map((_, i) => (
                    <div key={i} className="p-4 bg-gray-950/60 border border-gray-800 rounded-xl animate-pulse">
                      <div className="flex flex-col sm:flex-row sm:items-center justify-between">
                        <div className="flex flex-col gap-2 flex-1">
                          <div className="h-4 bg-gray-800 rounded-md w-3/4" />
                          <div className="flex items-center gap-3 mt-1">
                            <div className="h-3 bg-gray-800 rounded w-16" />
                            <div className="h-4 bg-gray-800 rounded w-8" />
                            <div className="h-3 bg-gray-800 rounded w-20" />
                          </div>
                        </div>
                        <div className="h-5 w-5 bg-gray-800 rounded hidden sm:block shrink-0 ml-2" />
                      </div>
                    </div>
                  ))}
                </div>
              ) : recentIncidents.length === 0 ? (
                <div className="flex items-center justify-center h-full text-gray-500 text-sm">
                  No recent incidents found.
                </div>
              ) : (
                <div className="flex flex-col gap-2">
                  {recentIncidents.map((incident) => (
                    <div 
                      key={incident.id} 
                      onClick={() => router.push(`/incident/${incident.id}`)}
                      className="group flex flex-col sm:flex-row sm:items-center justify-between p-4 bg-gray-950/60 hover:bg-gray-800/80 border border-gray-800 hover:border-gray-700 rounded-xl cursor-pointer transition-all"
                    >
                      <div className="flex flex-col">
                        <span className="font-semibold text-gray-200 line-clamp-1">{incident.title}</span>
                        <div className="flex items-center gap-3 mt-1 text-xs text-gray-500">
                          <span className="font-mono">{incident.id.split('-')[1] || incident.id}</span>
                          <span className={`font-bold px-2 py-0.5 rounded ${incident.severity === 'P1' ? 'bg-red-900/50 text-red-400' : 'bg-orange-900/50 text-orange-400'}`}>
                            {incident.severity}
                          </span>
                          <span className="capitalize text-[10px] sm:text-xs">
                            {incident.status.replace('_', ' ')}
                          </span>
                        </div>
                      </div>
                      <ChevronRight className="w-5 h-5 text-gray-600 group-hover:text-blue-400 transition-colors hidden sm:block shrink-0 ml-2" />
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>

        </div>
      </motion.div>
    </main>
  );
}
