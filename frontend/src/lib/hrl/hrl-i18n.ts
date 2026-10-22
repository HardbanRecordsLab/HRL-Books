/**
 * HRL — wspólny runtime tłumaczeń interfejsu (kopiowany do aplikacji bez własnego i18n).
 *
 * Teksty w komponentach mogą być po polsku albo po angielsku. Słownik to pary [pl, en]; dla języka docelowego
 * runtime podmienia tekst każdego węzła i atrybutu (placeholder, title, alt, aria-label), jeśli pasuje do którejś
 * strony pary. MutationObserver tłumaczy to, co React doda lub zmieni później — zanim przeglądarka namaluje klatkę,
 * więc nie ma mignięcia tekstu w złym języku. Oryginały są pamiętane, więc przełączanie działa w obie strony.
 *
 * Język: ?lang= w adresie > ciasteczko hrl_lang (wspólne dla *.hardbanrecordslab.online) > localStorage > angielski.
 * Elementy z translate="no" (lub klasą notranslate) są pomijane — to treści użytkowników, nie interfejs.
 * Klucze ze znacznikiem {} dopasowują tekst zmienny, np. ["Znaleziono {} utworów", "Found {} tracks"].
 */
export type Lang = 'en' | 'pl';

export interface HrlI18nOptions {
  /** Pary [polski, angielski]. */
  pairs: Array<[string, string]>;
  /** Klucz localStorage, np. 'mp_lang'. */
  storageKey: string;
  /** Tytuł karty i opis w obu językach (opcjonalnie). */
  title?: { en: string; pl: string };
  description?: { en: string; pl: string };
}

const COOKIE = 'hrl_lang';
const ATTRS = ['placeholder', 'title', 'alt', 'aria-label', 'aria-description'];
const META_KEYS = new Set(['description', 'og:title', 'og:description', 'twitter:title', 'twitter:description']);
const SKIP_TAGS = new Set(['SCRIPT', 'STYLE', 'TEXTAREA', 'NOSCRIPT', 'CODE', 'PRE']);
const MONTHS: Record<string, string> = {
  stycznia: 'January', lutego: 'February', marca: 'March', kwietnia: 'April', maja: 'May', czerwca: 'June',
  lipca: 'July', sierpnia: 'August', września: 'September', października: 'October', listopada: 'November', grudnia: 'December',
  styczeń: 'January', luty: 'February', marzec: 'March', kwiecień: 'April', maj: 'May', czerwiec: 'June',
  lipiec: 'July', sierpień: 'August', wrzesień: 'September', październik: 'October', listopad: 'November', grudzień: 'December',
};
const WEEKDAYS: Record<string, string> = {
  poniedziałek: 'Monday', wtorek: 'Tuesday', środa: 'Wednesday', czwartek: 'Thursday', piątek: 'Friday', sobota: 'Saturday', niedziela: 'Sunday',
};
const MONTH_RE = /\b(stycznia|lutego|marca|kwietnia|maja|czerwca|lipca|sierpnia|września|października|listopada|grudnia|styczeń|luty|marzec|kwiecień|maj|czerwiec|lipiec|sierpień|wrzesień|październik|listopad|grudzień)\b/gi;
const DAY_RE = /\b(poniedziałek|wtorek|środa|czwartek|piątek|sobota|niedziela)\b/gi;

type Listener = (lang: Lang) => void;
interface Pattern { re: RegExp; to: string }

let lang: Lang = 'en';
let opts: HrlI18nOptions | null = null;
let toEn = new Map<string, string>();
let toPl = new Map<string, string>();
let patEn: Pattern[] = [];
let patPl: Pattern[] = [];
const listeners = new Set<Listener>();
// Tryb zbierania brakujących tłumaczeń (QA): ?hrl_debug=1 — lista dostępna w window.__hrlMissing().
let debug = false;
const missing = new Set<string>();
let observer: MutationObserver | null = null;

const origText = new WeakMap<Text, string>();
const outText = new WeakMap<Text, string>();
const origAttr = new WeakMap<Element, Record<string, string>>();
const outAttr = new WeakMap<Element, Record<string, string>>();

const isLang = (v: unknown): v is Lang => v === 'en' || v === 'pl';

export function readLangCookie(): Lang | null {
  try {
    const m = document.cookie.match(/(?:^|;\s*)hrl_lang=(en|pl)\b/);
    return m ? (m[1] as Lang) : null;
  } catch {
    return null;
  }
}

export function writeLangCookie(l: Lang): void {
  try {
    const shared = /(^|\.)hardbanrecordslab\.online$/.test(window.location.hostname) ? ';domain=.hardbanrecordslab.online' : '';
    document.cookie = `${COOKIE}=${l};path=/;max-age=31536000;SameSite=Lax${shared}`;
  } catch {
    /* ciasteczka zablokowane */
  }
}

function resolveInitialLang(storageKey: string): Lang {
  try {
    const q = new URLSearchParams(window.location.search).get('lang');
    if (isLang(q)) {
      try { localStorage.setItem(storageKey, q); } catch { /* ignore */ }
      writeLangCookie(q);
      return q;
    }
  } catch { /* ignore */ }
  const c = readLangCookie();
  if (c) return c;
  try {
    const s = localStorage.getItem(storageKey);
    if (isLang(s)) return s;
  } catch { /* ignore */ }
  return 'en';
}

const norm = (s: string): string => s.replace(/ /g, ' ').replace(/\s+/g, ' ').trim();
const escapeRe = (s: string): string => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

function convertNumber(intPart: string, dec?: string): string {
  const i = intPart.replace(/[\s ]/g, '').replace(/\B(?=(\d{3})+(?!\d))/g, ',');
  return dec ? `${i}.${dec}` : i;
}

/** Daty, waluta i czas względny po polsku → angielski (tylko dla wersji angielskiej). */
function postProcessEn(s: string): string {
  let out = s;
  if (out.includes('zł')) {
    out = out.replace(/(\d{1,3}(?:[\s ]\d{3})+|\d+)(?:,(\d+))?\s?zł/g, (_m, i: string, d?: string) => `PLN ${convertNumber(i, d)}`);
  }
  out = out.replace(MONTH_RE, (m) => MONTHS[m.toLowerCase()] || m);
  out = out.replace(DAY_RE, (m) => WEEKDAYS[m.toLowerCase()] || m);
  out = out.replace(/(\d+) (sekund\w*|minut\w*|godzin\w*|dni|dzień|tygodn\w*|miesi\w+) temu/g, (_m, n: string, unit: string) => {
    const u = /^sek/.test(unit) ? 'second' : /^min/.test(unit) ? 'minute' : /^godz/.test(unit) ? 'hour' : /^dzie|^dni/.test(unit) ? 'day' : /^tydz/.test(unit) ? 'week' : 'month';
    return `${n} ${u}${n === '1' ? '' : 's'} ago`;
  });
  return out;
}

/** Tłumaczy cały tekst na język docelowy; null = brak zmiany. */
function lookup(raw: string): string | null {
  const key = norm(raw);
  if (!key || !/[A-Za-zĄ-ż]/.test(key)) return null;
  const map = lang === 'en' ? toEn : toPl;
  let res: string | null = null;
  const hit = map.get(key);
  if (hit !== undefined) {
    res = hit;
  } else {
    for (const p of lang === 'en' ? patEn : patPl) {
      const m = key.match(p.re);
      if (m) {
        let i = 0;
        // zmienne części wzorca też są tłumaczone, jeśli znajdą się w słowniku (np. tytuł strony w „{} — MasteringPro”)
        res = p.to.replace(/\{(\d*)\}/g, (_x, n: string) => {
          const g = m[n ? Number(n) : ++i] ?? '';
          const h = map.get(norm(g));
          return h !== undefined ? h : g;
        });
        break;
      }
    }
  }
  const base = res !== null ? res : key;
  const post = lang === 'en' ? postProcessEn(base) : base;
  if (post === key) {
    if (debug && res === null) missing.add(key);
    return null;
  }
  const lead = raw.match(/^\s*/)![0];
  const trail = raw.match(/\s*$/)![0];
  return lead + post + trail;
}

/** Linki do strony WordPressa: w wersji polskiej dostają prefiks /pl/. */
function hrefFor(o: string): string | null {
  if (lang !== 'pl') return null;
  const m = o.match(/^(https:\/\/hardbanrecordslab\.online)(\/[^?#]*)?([?#].*)?$/);
  if (!m) return null;
  const path = m[2] || '/';
  if (/^\/(pl(\/|$)|wp-|cdn-cgi|feed|sitemap|robots)/.test(path) || /\.(css|js|png|jpe?g|svg|webp|pdf|xml|txt|mp3|mp4)$/i.test(path)) return null;
  return `${m[1]}/pl${path}${m[3] || ''}`;
}

function skipped(el: Element | null): boolean {
  for (let n: Element | null = el; n; n = n.parentElement) {
    if (SKIP_TAGS.has(n.tagName)) return true;
    if (n.getAttribute('translate') === 'no' || n.classList.contains('notranslate') || n.getAttribute('contenteditable') === 'true') return true;
  }
  return false;
}

/** Ustawia węzeł tekstowy w języku bieżącym; nowy tekst wstawiony przez aplikację traktuje jako oryginał. */
function syncText(node: Text): void {
  const cur = node.nodeValue ?? '';
  let o = origText.get(node);
  const prevOut = outText.get(node);
  if (o === undefined || (cur !== o && cur !== prevOut)) {
    o = cur;
    origText.set(node, cur);
    outText.delete(node);
  }
  const t = skipped(node.parentElement) ? null : lookup(o);
  const want = t !== null ? t : o;
  if (want !== cur) node.nodeValue = want;
  if (want !== o) outText.set(node, want);
  else outText.delete(node);
}

function syncAttr(el: Element, name: string): void {
  const cur = el.getAttribute(name);
  if (cur === null) return;
  const origs = origAttr.get(el) || {};
  const outs = outAttr.get(el) || {};
  let o = origs[name];
  if (o === undefined || (cur !== o && cur !== outs[name])) {
    o = cur;
    origs[name] = cur;
    delete outs[name];
  }
  const t = skipped(el) ? null : name === 'href' ? hrefFor(o) : lookup(o);
  const want = t !== null ? t : o;
  if (want !== cur) el.setAttribute(name, want);
  if (want !== o) outs[name] = want;
  else delete outs[name];
  origAttr.set(el, origs);
  outAttr.set(el, outs);
}

function isButtonInput(el: Element): boolean {
  return el.tagName === 'INPUT' && /^(button|submit|reset)$/i.test((el as HTMLInputElement).type);
}

function isMetaText(el: Element): boolean {
  return el.tagName === 'META' && META_KEYS.has((el.getAttribute('name') || el.getAttribute('property') || '').toLowerCase());
}

function syncElementAttrs(el: Element): void {
  for (const a of ATTRS) {
    if (el.hasAttribute(a)) syncAttr(el, a);
  }
  if (isButtonInput(el) && el.hasAttribute('value')) syncAttr(el, 'value');
  if (isMetaText(el) && el.hasAttribute('content')) syncAttr(el, 'content');
  if (el.tagName === 'A' && el.hasAttribute('href')) syncAttr(el, 'href');
}

function walk(root: Node): void {
  if (root.nodeType === Node.TEXT_NODE) {
    syncText(root as Text);
    return;
  }
  if (root.nodeType !== Node.ELEMENT_NODE && root.nodeType !== Node.DOCUMENT_NODE && root.nodeType !== Node.DOCUMENT_FRAGMENT_NODE) return;
  if (root.nodeType === Node.ELEMENT_NODE) syncElementAttrs(root as Element);
  const tw = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT);
  let n: Node | null = tw.nextNode();
  while (n) {
    if (n.nodeType === Node.TEXT_NODE) syncText(n as Text);
    else syncElementAttrs(n as Element);
    n = tw.nextNode();
  }
}

function applyMeta(): void {
  if (!opts) return;
  document.documentElement.lang = lang;
  const ol = document.querySelector('meta[property="og:locale"]');
  if (ol) ol.setAttribute('content', lang === 'pl' ? 'pl_PL' : 'en_US');
  if (opts.title) document.title = opts.title[lang];
  if (opts.description) {
    const m = document.querySelector('meta[name="description"]');
    if (m) m.setAttribute('content', opts.description[lang]);
  }
}

function compile(key: string): RegExp {
  return new RegExp('^' + key.split('{}').map(escapeRe).join('(.+?)') + '$');
}

function buildDictionary(pairs: Array<[string, string]>): void {
  toEn = new Map();
  toPl = new Map();
  patEn = [];
  patPl = [];
  for (const [pl, en] of pairs) {
    const p = norm(pl);
    const e = norm(en);
    if (!p || !e) continue;
    if (p === e && !p.includes('{}')) continue;
    if (p.includes('{}') || e.includes('{}')) {
      patEn.push({ re: compile(p), to: en });
      patPl.push({ re: compile(e), to: pl });
    } else {
      toEn.set(p, en);
      toPl.set(e, pl);
    }
  }
}

function wrapDialogs(): void {
  const w = window as unknown as Record<string, unknown>;
  for (const name of ['alert', 'confirm', 'prompt'] as const) {
    const orig = (w[name] as (...a: unknown[]) => unknown).bind(window);
    (w[name] as unknown) = (msg?: unknown, ...rest: unknown[]) => {
      if (typeof msg === 'string') {
        const t = lookup(msg);
        if (t !== null) msg = t;
      }
      return orig(msg, ...rest);
    };
  }
}

/** Tłumaczy pojedynczy tekst (np. komunikat składany w kodzie) na język bieżący. */
export function tr(text: string): string {
  const t = lookup(text);
  return t !== null ? t : text;
}

export function getLang(): Lang {
  return lang;
}

export function setLang(next: Lang): void {
  if (next === lang) return;
  lang = next;
  try { if (opts) localStorage.setItem(opts.storageKey, next); } catch { /* ignore */ }
  writeLangCookie(next);
  applyMeta();
  walk(document.documentElement);
  listeners.forEach((l) => l(lang));
}

export function subscribeLang(l: Listener): () => void {
  listeners.add(l);
  return () => listeners.delete(l);
}

/** Wywołaj raz, przed render() aplikacji. */
export function initHrlI18n(options: HrlI18nOptions): void {
  if (opts) return;
  opts = options;
  buildDictionary(options.pairs);
  lang = resolveInitialLang(options.storageKey);
  try {
    debug = new URLSearchParams(window.location.search).has('hrl_debug') || localStorage.getItem('hrl_debug') === '1';
  } catch { /* ignore */ }
  if (debug) (window as unknown as Record<string, unknown>).__hrlMissing = () => Array.from(missing);
  applyMeta();
  wrapDialogs();
  observer = new MutationObserver((records) => {
    for (const r of records) {
      if (r.type === 'characterData') {
        if (r.target.nodeType === Node.TEXT_NODE) syncText(r.target as Text);
      } else if (r.type === 'attributes') {
        const el = r.target as Element;
        const name = r.attributeName || '';
        if (ATTRS.includes(name) || (name === 'value' && isButtonInput(el)) || (name === 'content' && isMetaText(el)) || (name === 'href' && el.tagName === 'A')) syncAttr(el, name);
      } else {
        r.addedNodes.forEach((n) => walk(n));
      }
    }
  });
  const start = () => {
    walk(document.documentElement);
    observer!.observe(document.documentElement, {
      subtree: true,
      childList: true,
      characterData: true,
      attributes: true,
      attributeFilter: [...ATTRS, 'value', 'content', 'href'],
    });
  };
  if (document.body) start();
  else document.addEventListener('DOMContentLoaded', start, { once: true });
}
