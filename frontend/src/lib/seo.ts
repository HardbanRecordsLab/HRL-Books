// Per-route head tags for the SPA (title, description, canonical, robots, JSON-LD). Search engines render the page,
// so tags set here are seen. Returns a cleanup that puts the head back the way it was.
export type Seo = { title?: string; description?: string; canonical?: string; robots?: string; jsonLd?: object };

function meta(name: string): HTMLMetaElement {
  let el = document.head.querySelector<HTMLMetaElement>(`meta[name="${name}"]`);
  if (!el) { el = document.createElement("meta"); el.name = name; document.head.appendChild(el); }
  return el;
}

export function setSeo(s: Seo): () => void {
  const prevTitle = document.title;
  const desc = meta("description"), robots = meta("robots");
  const prevDesc = desc.getAttribute("content"), prevRobots = robots.getAttribute("content");
  const added: HTMLElement[] = [];
  if (s.title) document.title = s.title;
  if (s.description) desc.setAttribute("content", s.description.slice(0, 300));
  robots.setAttribute("content", s.robots || "index, follow");
  if (s.canonical) {
    const link = document.createElement("link");
    link.rel = "canonical"; link.href = s.canonical; link.dataset.seo = "1";
    document.head.appendChild(link); added.push(link);
    for (const [prop, val] of [["og:url", s.canonical], ["og:title", s.title || ""], ["og:description", s.description || ""]] as const) {
      if (!val) continue;
      const og = document.createElement("meta");
      og.setAttribute("property", prop); og.content = val; og.dataset.seo = "1";
      document.head.appendChild(og); added.push(og);
    }
  }
  if (s.jsonLd) {
    const script = document.createElement("script");
    script.type = "application/ld+json"; script.dataset.seo = "1";
    script.textContent = JSON.stringify(s.jsonLd);
    document.head.appendChild(script); added.push(script);
  }
  return () => {
    document.title = prevTitle;
    if (prevDesc !== null) desc.setAttribute("content", prevDesc);
    if (prevRobots !== null) robots.setAttribute("content", prevRobots); else robots.remove();
    added.forEach((el) => el.remove());
  };
}

// Pages behind a login: tell crawlers not to index the login wall / empty shell.
export const NOINDEX: Seo = { robots: "noindex, follow" };
