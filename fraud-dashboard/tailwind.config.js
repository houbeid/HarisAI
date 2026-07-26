/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      // Palette figée d'après la maquette validée (captures Claude Design) :
      // Block=rouge, Review=ambre, Approve=vert. Ne pas redéfinir ces
      // couleurs ailleurs dans le code (composants, styles inline) — tout
      // usage de couleur de sévérité doit passer par ces tokens, pour
      // qu'un changement de palette se fasse en un seul endroit.
      colors: {
        severity: {
          danger: { bg: '#FAECE7', border: '#D85A30', text: '#712B13' },
          warning: { bg: '#FAEEDA', border: '#BA7517', text: '#633806' },
          success: { bg: '#EAF3DE', border: '#639922', text: '#27500A' },
        },
        status: {
          neutral: { bg: '#F1EFE8', text: '#444441' },
          info: { bg: '#E6F1FB', text: '#0C447C' },
          muted: { bg: '#EEEDFE', text: '#3C3489' },
        },
      },
    },
  },
  plugins: [],
};
