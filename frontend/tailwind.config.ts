import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        background: "#0a0f1a",
        panel: "#0f1629",
        border: "#1e2d4a",
        accent: "#3b82f6",
        agent: {
          idle: "#6b7280",
          investigating: "#eab308",
          challenging: "#3b82f6",
          done: "#22c55e",
          error: "#ef4444",
        }
      },
      fontFamily: {
        mono: ["JetBrains Mono", "Fira Code", "monospace"],
      },
    },
  },
  plugins: [],
};

export default config;
