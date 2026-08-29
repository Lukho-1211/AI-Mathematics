/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./app/**/*.{js,ts,jsx,tsx}",
    "./components/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        ink: {
          950: "#070b14",
          900: "#0b1220",
          800: "#121a2b",
          700: "#1a2438",
        },
        accent: {
          DEFAULT: "#5b8cff",
          soft: "#8eb6ff",
          warm: "#f5c542",
        },
      },
      fontFamily: {
        sans: ["var(--font-geist-sans)", "system-ui", "sans-serif"],
        display: ["var(--font-display)", "Georgia", "serif"],
      },
      boxShadow: {
        panel: "0 10px 40px rgba(0,0,0,0.35)",
      },
    },
  },
  plugins: [],
};
