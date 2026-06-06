import { useEffect, useRef } from "react";
import { SwarmEvent } from "../lib/types";

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
        {events.map((ev, i) => (
          <div key={i} className="text-gray-300 break-words border-b border-gray-900 pb-2">
            <span className="text-emerald-500 mr-2">[{new Date().toLocaleTimeString()}]</span>
            <span className="text-blue-400 font-bold mr-2">{ev.event}:</span>
            <span className="text-gray-400">
              {JSON.stringify(ev.payload, null, 2)}
            </span>
          </div>
        ))}
        {events.length === 0 && (
          <div className="text-gray-600 italic">Waiting for swarm events...</div>
        )}
      </div>
    </div>
  );
}
