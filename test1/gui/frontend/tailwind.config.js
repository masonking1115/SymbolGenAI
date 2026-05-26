/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: [
          "Inter",
          "-apple-system",
          "BlinkMacSystemFont",
          "Segoe UI",
          "Roboto",
          "Helvetica Neue",
          "sans-serif",
        ],
      },
      colors: {
        ink: {
          900: "#0F1115",
          700: "#363B45",
          500: "#5C6470",
          300: "#A6ACB5",
        },
        rail: "#FAFAFB",
        edge: "#E6E8EC",
        ok: "#1F9D55",
        warn: "#D08400",
        err: "#C53030",
      },
    },
  },
  plugins: [],
};
