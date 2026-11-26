/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#080b12",
        panel: "#111620",
        cyan: "#78e7ee",
        amber: "#efc66f",
      },
    },
  },
  plugins: [],
};
