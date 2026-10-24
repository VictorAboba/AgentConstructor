/** UI language for explanatory text (hints, guide, template notes). Labels and controls stay English. */
export type Lang = 'en' | 'ru'
const KEY = 'ac.lang'

function detect(): Lang {
  try {
    const saved = localStorage.getItem(KEY)
    if (saved === 'en' || saved === 'ru') return saved
  } catch { /* storage unavailable */ }
  return navigator.language?.toLowerCase().startsWith('ru') ? 'ru' : 'en'
}

export const LANG: Lang = detect()

/** Saves the choice and reloads, so module-level text (HINTS) is rebuilt in the new language. */
export function setLang(lang: Lang) {
  try { localStorage.setItem(KEY, lang) } catch { /* storage unavailable */ }
  window.location.reload()
}

export const tr = (en: string, ru: string) => (LANG === 'ru' ? ru : en)
