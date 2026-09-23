/** @type {import('tailwindcss').Config} */
//
// Design-Tokens. Vorher stand hier `extend: {}` — also reines Standard-Tailwind,
// und genau daran erkennt man ein Projekt, in dem niemand eine Entscheidung
// getroffen hat: slate-950 auf indigo-600, System-Schrift, alles gleich rund.
//
// Grundsatz dieser Palette: fast schwarz und NEUTRAL (nicht das blaustichige
// slate), Farbe ausschliesslich als Signal. Die Farbtoene stammen von den
// Pokemon-Energietypen — aber jedem ist eine Bedeutung zugeordnet, statt sie
// dekorativ zu streuen:
//
//   grass    Gewinn, alles Bestaetigte
//   fire     Verlust, Dringlichkeit, auslaufende Zeit
//   water    Hinweise, neutrale Hervorhebung
//   psychic  Schaetzwerte (Marktpreis, schwache Stufe) — bewusst "unsicher"
//   electric Aufmerksamkeit ohne Wertung
//
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      colors: {
        // Flaechen: warm-neutrales Schwarz, kein Blaustich.
        ink: {
          950: "#0A0B0D",
          900: "#0F1114",
          850: "#14171B",
          800: "#191D22",
          700: "#23282F",
          600: "#2E343C",
        },
        paper: {
          DEFAULT: "#E7E9EC",
          muted: "#8C939E",
          dim: "#5B636E",
        },
        grass: { DEFAULT: "#35C08A", dim: "#1C6B4E" },
        fire: { DEFAULT: "#FF5A3C", dim: "#8A2E1E" },
        water: { DEFAULT: "#38A3FF", dim: "#1B5C93" },
        psychic: { DEFAULT: "#A97BFF", dim: "#5C3F91" },
        electric: { DEFAULT: "#F5C542", dim: "#8A6E16" },
      },
      fontFamily: {
        sans: ["Inter", "system-ui", "sans-serif"],
        // Zahlen gehoeren in Monospace: nur so stehen Stellen untereinander,
        // und genau das macht den Unterschied zwischen "Webseite" und
        // "Handelsterminal" aus.
        mono: ["'JetBrains Mono'", "ui-monospace", "monospace"],
      },
      fontSize: {
        "2xs": ["0.6875rem", { lineHeight: "1rem" }],
      },
      borderRadius: {
        // Kaum Rundung: Kanten wirken praezise, weiche Ecken wirken gefaellig.
        DEFAULT: "3px",
        sm: "2px",
        md: "4px",
      },
      letterSpacing: {
        wider: "0.08em",
        widest: "0.18em",
      },
    },
  },
  plugins: [],
};
