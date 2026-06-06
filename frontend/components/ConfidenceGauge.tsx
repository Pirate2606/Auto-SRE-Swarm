import { motion } from "framer-motion";

export function ConfidenceGauge({ confidence }: { confidence: number }) {
  const percentage = Math.round(confidence * 100);
  
  let color = "text-red-500";
  let stroke = "stroke-red-500";
  if (percentage >= 70) {
    color = "text-emerald-500";
    stroke = "stroke-emerald-500";
  } else if (percentage >= 40) {
    color = "text-yellow-500";
    stroke = "stroke-yellow-500";
  }

  const radius = 36;
  const circumference = 2 * Math.PI * radius;
  const strokeDashoffset = circumference - (percentage / 100) * circumference;

  return (
    <div className="relative flex items-center justify-center w-24 h-24">
      <svg className="w-full h-full transform -rotate-90">
        <circle
          className="stroke-gray-800"
          strokeWidth="8"
          fill="transparent"
          r={radius}
          cx="48"
          cy="48"
        />
        <motion.circle
          className={`${stroke} transition-all duration-1000 ease-out`}
          strokeWidth="8"
          strokeLinecap="round"
          fill="transparent"
          r={radius}
          cx="48"
          cy="48"
          initial={{ strokeDashoffset: circumference }}
          animate={{ strokeDashoffset }}
          style={{ strokeDasharray: circumference }}
        />
      </svg>
      <div className="absolute flex flex-col items-center justify-center">
        <span className={`text-xl font-black ${color}`}>{percentage}%</span>
      </div>
    </div>
  );
}
