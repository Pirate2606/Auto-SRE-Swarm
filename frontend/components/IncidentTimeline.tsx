import { TimelineEntry } from "../lib/types";
import { format } from "date-fns";

export function IncidentTimeline({ timeline }: { timeline: TimelineEntry[] }) {
  if (!timeline || timeline.length === 0) {
    return (
      <div className="flex flex-col h-full bg-gray-950 p-4">
        <h2 className="text-sm font-bold text-gray-400 uppercase tracking-wider mb-4">Investigation Timeline</h2>
        <div className="flex-1 flex items-center justify-center text-gray-600 italic">
          Waiting for events...
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full bg-gray-950 p-4">
      <h2 className="text-sm font-bold text-gray-400 uppercase tracking-wider mb-4">Investigation Timeline</h2>
      <div className="flex-1 overflow-y-auto pr-2 relative">
        <div className="absolute left-3 top-2 bottom-2 w-px bg-gray-800" />
        
        <div className="space-y-6 relative">
          {timeline.map((entry, i) => (
            <div key={i} className="flex gap-4 items-start">
              <div className="relative mt-1">
                <div className="w-6 h-6 rounded-full bg-gray-900 border-2 border-emerald-500 flex items-center justify-center z-10 relative" />
              </div>
              <div className="flex-1">
                <div className="flex items-baseline gap-2 mb-1">
                  <span className="text-emerald-400 font-bold text-sm">
                    {entry.agent || "System"}
                  </span>
                  <span className="text-xs text-gray-500 font-mono">
                    {format(new Date(entry.timestamp), "HH:mm:ss.SSS")}
                  </span>
                </div>
                <p className="text-sm text-gray-300">{entry.event}</p>
                {entry.round_number && (
                  <span className="inline-block mt-1 px-2 py-0.5 bg-gray-800 text-gray-400 text-[10px] rounded border border-gray-700">
                    Round {entry.round_number}
                  </span>
                )}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
