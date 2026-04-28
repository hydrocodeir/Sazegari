/** @type {import('tailwindcss').Config} */
module.exports = {
  prefix: "tw-",
  content: [
    "./app/templates/**/*.html",
    "./app/static/js/**/*.js"
  ],
  corePlugins: {
    preflight: false
  },
  theme: {
    extend: {
      fontFamily: {
        sans: [
          "Vazirmatn",
          "ui-sans-serif",
          "system-ui",
          "-apple-system",
          "BlinkMacSystemFont",
          "Segoe UI",
          "sans-serif"
        ]
      },
      colors: {
        hydro: {
          ink: "#10231f",
          deep: "#123a36",
          teal: "#14746f",
          water: "#0ea5a4",
          mint: "#c9f2e8",
          reed: "#d8a31f",
          clay: "#b85c38",
          cloud: "#f5fbf9"
        }
      },
      boxShadow: {
        "hydro-card": "0 18px 45px rgba(16, 35, 31, 0.08)",
        "hydro-soft": "0 10px 28px rgba(20, 116, 111, 0.14)"
      }
    }
  }
};
