import { useSyncExternalStore } from 'react';
import { getLang, setLang, subscribeLang, type Lang } from './hrl-i18n';

/** Przełącznik EN | PL — jednakowy we wszystkich aplikacjach HRL. Kolory dziedziczy z otoczenia (currentColor). */
export default function HrlLangSwitch({ className = '', accent = '#c8a96e' }: { className?: string; accent?: string }) {
  const lang = useSyncExternalStore(subscribeLang, getLang, getLang);
  const item = (code: Lang) => (
    <button
      key={code}
      type="button"
      translate="no"
      onClick={() => setLang(code)}
      aria-pressed={lang === code}
      aria-label={code === 'en' ? 'English' : 'Polski'}
      style={{
        padding: '4px 9px',
        borderRadius: 999,
        border: 0,
        cursor: 'pointer',
        font: '700 11px/1 system-ui, sans-serif',
        letterSpacing: '.08em',
        background: lang === code ? accent : 'transparent',
        color: lang === code ? '#0b0b0b' : 'inherit',
        opacity: lang === code ? 1 : 0.75,
      }}
    >
      {code.toUpperCase()}
    </button>
  );
  return (
    <div
      className={className}
      role="group"
      aria-label="Language"
      translate="no"
      style={{ display: 'inline-flex', alignItems: 'center', gap: 2, padding: 2, borderRadius: 999, border: `1px solid ${accent}66` }}
    >
      {item('en')}
      {item('pl')}
    </div>
  );
}
