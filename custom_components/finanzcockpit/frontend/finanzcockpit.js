// Frontend des Finanzcockpits. Wird von der Integration automatisch geladen.
//
// - finanzcockpit-donut-card: Kuchendiagramm (Donut) für beliebige Sensoren
// - finanzcockpit-verlauf-card: Liniendiagramm der Vorsorge-Simulation
// - Dashboard-Strategie «custom:finanzcockpit»: baut das Dashboard aus den
//   vorhandenen Sensoren zusammen, neue Konten erscheinen ohne Anpassung

const PLATTFORM = "finanzcockpit";
const SUMME = `sensor.${PLATTFORM}_summe_`;
const SIM = `${PLATTFORM}_sim_`;
const VERLAUF = `sensor.${SIM}verlauf`;

// Farben wie im Logo, ergänzt für sechs Anlageklassen und vier Währungen
const ANLAGEKLASSEN = [
  ["liquiditaet", "Liquidität", "#3BA7E0"],
  ["obligationen", "Obligationen", "#8E7CC3"],
  ["aktien", "Aktien", "#2FB67C"],
  ["immobilien", "Immobilien", "#E8A33D"],
  ["rohstoffe", "Rohstoffe", "#B5835A"],
  ["krypto", "Krypto", "#F7931A"],
];
const WAEHRUNGSFARBEN = { chf: "#D9534F", eur: "#3B6FE0", usd: "#2FB67C", btc: "#F7931A" };
const ERSATZFARBEN = ["#3BA7E0", "#2FB67C", "#E8A33D", "#8E7CC3", "#D9534F", "#B5835A"];

// Tabelle aller Konten; Home Assistant rendert das Template serverseitig
const KONTENTABELLE = `| Konto | Topf | Saldo | in CHF |
|:--|:--|--:|--:|
{% for e in integration_entities('${PLATTFORM}') | sort -%}
{%- set s = states[e] -%}
{#- Nur Konto-Sensoren; Summen und Simulation haben keine konto_id -#}
{%- if s and s.attributes.konto_id is defined -%}
{%- set format = '{:,.8f}' if s.attributes.unit_of_measurement == 'BTC' else '{:,.0f}' -%}
| {{ s.name }} | {{ s.attributes.topf }} | {{ format.format(s.state | float(0)) | replace(',', "'") }} {{ s.attributes.unit_of_measurement }} | {{ '{:,.0f}'.format(s.attributes.wert_chf or 0) | replace(',', "'") }} |
{% endif -%}
{% endfor -%}
| **Total** | | | **{{ '{:,.0f}'.format(states('sensor.${PLATTFORM}_summe_total') | float(0)) | replace(',', "'") }}** |`;

// Simulation: Reihenfolge wie in simulation.py und sensor.py
const REGLER = [
  "pension_er",
  "pension_sie",
  "pensum_er",
  "pensum_er_ab",
  "pensum_sie",
  "pensum_sie_ab",
  "ahv_alter_er",
  "ahv_alter_sie",
  "kapitalbezug_er",
  "kapitalbezug_sie",
  "einkauf_er",
  "einkauf_sie",
  "amortisation",
];
const KENNZAHLEN = [
  "vorsorgeluecke",
  "frei_pension_er",
  "frei_pension_sie",
  "frei_ende",
  "tiefster_stand",
  "erstes_negatives_jahr",
  "belehnung",
  "tragbarkeit",
  "nettovermoegen_ende",
  "steuern_summe",
];
const REIHEN = {
  frei_real: ["Freies Vermögen", "#3BA7E0"],
  hypothek_real: ["Hypothek", "#E8A33D"],
  nettovermoegen_real: ["Nettovermögen", "#8E7CC3"],
  renten_real: ["Renten", "#2FB67C"],
  ausgaben_real: ["Ausgaben", "#D9534F"],
};

// Vergleich aller Szenarien; Home Assistant rendert das Template serverseitig
const VERGLEICHSTABELLE = `{%- macro f(v, art) -%}
{%- if v is none -%}–{%- elif art == 'chf' -%}{{ '{:,.0f}'.format(v) | replace(',', "'") }}
{%- elif art == 'pct' -%}{{ '{:.1f}'.format(v) }} %{%- else -%}{{ v }}{%- endif -%}
{%- endmacro -%}
{%- set sz = state_attr('sensor.${SIM}vergleich', 'szenarien') or [] -%}
| Kennzahl |{% for s in sz %} {{ '**' ~ s.id ~ ' ◀**' if s.aktiv else s.id }} |{% endfor %}
|:--|{% for s in sz %}--:|{% endfor %}
{% for k in [
  ['vorsorgeluecke', 'Vorsorgelücke pro Monat', 'chf'],
  ['frei_pension_er', 'Freies Vermögen bei Pension Er', 'chf'],
  ['frei_pension_sie', 'Freies Vermögen bei Pension Sie', 'chf'],
  ['frei_ende', 'Freies Vermögen am Ende', 'chf'],
  ['tiefster_stand', 'Tiefster Stand (nominal)', 'chf'],
  ['erstes_negatives_jahr', 'Vermögen aufgebraucht', 'text'],
  ['belehnung', 'Belehnung bei Pension Er', 'pct'],
  ['tragbarkeit', 'Tragbarkeit im Ruhestand', 'pct'],
  ['nettovermoegen_ende', 'Nettovermögen am Ende', 'chf'],
  ['steuern_summe', 'Steuern total (nominal)', 'chf'],
] -%}
| {{ k[1] }} |{% for s in sz %} {{ f(s[k[0]], k[2]) }} |{% endfor %}
{% endfor %}
{% for s in sz %}
- **{{ s.id }}**: {{ s.name }}{% for w in s.warnungen %} ⚠️ {{ w }}{% endfor %}
{%- endfor %}

Ohne Regler, so wie die Szenarien in simulation.yaml stehen. Beträge in heutigen CHF.`;

const WARNUNGEN = `{%- set w = state_attr('${VERLAUF}', 'warnungen') -%}
{%- if w %}{% for t in w %}⚠️ {{ t }}
{% endfor %}{% else %}✅ Vermögen reicht, Tragbarkeit erfüllt.{% endif %}
{%- if state_attr('${VERLAUF}', 'angepasst') %}

*Regler weichen vom Szenario ab.*{% endif %}`;

const escape = (text) =>
  String(text).replace(
    /[&<>"']/g,
    (z) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[z],
  );

class FinanzcockpitDonutCard extends HTMLElement {
  static getStubConfig() {
    return {
      title: "Anlageklassen",
      entities: ANLAGEKLASSEN.map(([klasse]) => `${SUMME}anlageklasse_${klasse}`),
    };
  }

  setConfig(config) {
    if (!Array.isArray(config.entities) || config.entities.length === 0) {
      throw new Error("'entities' muss eine Liste von Sensoren sein");
    }
    this._config = {
      ...config,
      entities: config.entities.map((e) => (typeof e === "string" ? { entity: e } : e)),
    };
    this._signatur = undefined;
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    this._render();
  }

  getCardSize() {
    return 5;
  }

  getGridOptions() {
    return { columns: 6, min_columns: 4, rows: "auto" };
  }

  _segmente() {
    return this._config.entities
      .map((e, i) => {
        const state = this._hass.states[e.entity];
        return {
          entity: e.entity,
          name: e.name ?? state?.attributes.friendly_name ?? e.entity,
          farbe: e.color ?? ERSATZFARBEN[i % ERSATZFARBEN.length],
          wert: Number(state?.state),
          einheit: state?.attributes.unit_of_measurement ?? "",
        };
      })
      .filter((s) => Number.isFinite(s.wert) && s.wert > 0);
  }

  _render() {
    if (!this._config || !this._hass) return;
    const segmente = this._segmente();
    // Nur neu zeichnen, wenn sich die angezeigten Werte geändert haben
    const signatur = JSON.stringify([segmente, this._hass.locale?.language]);
    if (signatur === this._signatur) return;
    this._signatur = signatur;

    const sprache = this._hass.locale?.language ?? "de-CH";
    const zahl = new Intl.NumberFormat(sprache, { maximumFractionDigits: 0 });
    const prozent = new Intl.NumberFormat(sprache, { maximumFractionDigits: 1 });
    const total = segmente.reduce((summe, s) => summe + s.wert, 0);
    const einheit = segmente[0]?.einheit ?? "";

    // Kreisumfang 100, damit sich die Anteile direkt als Strichlänge eignen
    const radius = 100 / (2 * Math.PI);
    const luecke = segmente.length > 1 ? 0.6 : 0;
    let start = 0;
    const boegen = segmente
      .map((s) => {
        const anteil = (s.wert / total) * 100;
        const laenge = Math.max(anteil - luecke, 0.1);
        const bogen = `<circle class="bogen" data-entity="${escape(s.entity)}"
          r="${radius}" cx="21" cy="21" stroke="${escape(s.farbe)}"
          stroke-dasharray="${laenge} ${100 - laenge}" stroke-dashoffset="${25 - start}">
          <title>${escape(s.name)}: ${zahl.format(s.wert)} ${escape(s.einheit)}</title></circle>`;
        start += anteil;
        return bogen;
      })
      .join("");

    const legende = segmente
      .map(
        (s) => `<li data-entity="${escape(s.entity)}">
          <span class="punkt" style="background:${escape(s.farbe)}"></span>
          <span class="name">${escape(s.name)}</span>
          <span class="wert">${zahl.format(s.wert)} ${escape(s.einheit)}</span>
          <span class="anteil">${prozent.format((s.wert / total) * 100)} %</span>
        </li>`,
      )
      .join("");

    const titel = this._config.title ? `<h1 class="titel">${escape(this._config.title)}</h1>` : "";
    const inhalt = segmente.length
      ? `<div class="diagramm">
          <svg viewBox="0 0 42 42" role="img" aria-label="${escape(this._config.title ?? "")}">
            <circle class="ring" r="${radius}" cx="21" cy="21"></circle>
            ${boegen}
            <text x="21" y="20.5" class="total">${zahl.format(total)}</text>
            <text x="21" y="25" class="einheit">${escape(einheit)}</text>
          </svg>
        </div>
        <ul class="legende">${legende}</ul>`
      : `<p class="leer">Keine Werte vorhanden</p>`;

    if (!this.shadowRoot) this.attachShadow({ mode: "open" });
    this.shadowRoot.innerHTML = `
      <style>
        ha-card { padding: 16px; height: 100%; box-sizing: border-box; }
        .titel { margin: 0 0 12px; font-size: 16px; font-weight: 500; color: var(--primary-text-color); }
        .diagramm { max-width: 220px; margin: 0 auto; }
        svg { display: block; width: 100%; }
        circle { fill: transparent; stroke-width: 5; }
        .ring { stroke: var(--divider-color, #e0e0e0); }
        .bogen { cursor: pointer; transition: stroke-width 0.15s; }
        .bogen:hover { stroke-width: 6; }
        text { text-anchor: middle; fill: var(--primary-text-color); }
        .total { font-size: 5px; font-weight: 600; }
        .einheit { font-size: 3px; fill: var(--secondary-text-color); }
        .legende { list-style: none; margin: 16px 0 0; padding: 0; }
        .legende li { display: grid; grid-template-columns: 12px minmax(0, 1fr) auto auto; gap: 8px;
          align-items: center; padding: 4px 0; cursor: pointer; color: var(--primary-text-color); }
        .punkt { width: 12px; height: 12px; border-radius: 50%; }
        .name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        .wert, .anteil { white-space: nowrap; font-variant-numeric: tabular-nums; }
        .anteil { min-width: 3.5em; text-align: right; color: var(--secondary-text-color); }
        .leer { color: var(--secondary-text-color); }
      </style>
      <ha-card>${titel}${inhalt}</ha-card>`;

    this.shadowRoot.querySelectorAll("[data-entity]").forEach((element) =>
      element.addEventListener("click", () =>
        this.dispatchEvent(
          new CustomEvent("hass-more-info", {
            detail: { entityId: element.dataset.entity },
            bubbles: true,
            composed: true,
          }),
        ),
      ),
    );
  }
}

// Rundet eine Schrittweite auf 1, 2, 2.5 oder 5 × 10^n
const runderSchritt = (spanne) => {
  const roh = spanne / 4;
  const basis = 10 ** Math.floor(Math.log10(roh));
  return [1, 2, 2.5, 5, 10].map((f) => f * basis).find((s) => s >= roh);
};

class FinanzcockpitVerlaufCard extends HTMLElement {
  static getStubConfig() {
    return { title: "Freies Vermögen", entity: VERLAUF, reihen: ["frei_real", "hypothek_real"] };
  }

  setConfig(config) {
    if (!config.entity) throw new Error("'entity' fehlt (z.B. sensor.finanzcockpit_sim_verlauf)");
    const reihen = (config.reihen ?? ["frei_real", "hypothek_real"]).map((r) =>
      typeof r === "string" ? { schluessel: r } : r,
    );
    this._config = {
      ...config,
      reihen: reihen.map((r, i) => ({
        schluessel: r.schluessel,
        name: r.name ?? REIHEN[r.schluessel]?.[0] ?? r.schluessel,
        farbe: r.color ?? REIHEN[r.schluessel]?.[1] ?? ERSATZFARBEN[i % ERSATZFARBEN.length],
      })),
    };
    this._signatur = undefined;
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    this._render();
  }

  getCardSize() {
    return 6;
  }

  getGridOptions() {
    return { columns: 12, min_columns: 6, rows: "auto" };
  }

  _render() {
    if (!this._config || !this._hass) return;
    const state = this._hass.states[this._config.entity];
    const jahre = state?.attributes.jahre ?? [];
    const signatur = JSON.stringify([jahre, state?.attributes.pension_er, state?.attributes.pension_sie, this._hass.locale?.language]);
    if (signatur === this._signatur) return;
    this._signatur = signatur;

    const sprache = this._hass.locale?.language ?? "de-CH";
    const zahl = new Intl.NumberFormat(sprache, { maximumFractionDigits: 0 });
    const kurz = new Intl.NumberFormat(sprache, { maximumFractionDigits: 1 });
    const reihen = this._config.reihen;
    const titel = this._config.title ? `<h1 class="titel">${escape(this._config.title)}</h1>` : "";

    if (!this.shadowRoot) this.attachShadow({ mode: "open" });
    if (jahre.length < 2) {
      this.shadowRoot.innerHTML = `<ha-card style="padding:16px">${titel}<p>Keine Werte vorhanden</p></ha-card>`;
      return;
    }

    // Zeichenfläche in SVG-Einheiten; die Grafik skaliert mit der Kartenbreite
    const B = 600, H = 240, L = 48, R = 8, O = 10, U = 22;
    const werte = jahre.flatMap((j) => reihen.map((r) => Number(j[r.schluessel]) || 0));
    let min = Math.min(0, ...werte);
    let max = Math.max(0, ...werte);
    if (max === min) max = min + 1;
    const schritt = runderSchritt(max - min);
    min = Math.floor(min / schritt) * schritt;
    max = Math.ceil(max / schritt) * schritt;
    const erstes = jahre[0].jahr;
    const letztes = jahre[jahre.length - 1].jahr;
    const x = (jahr) => L + ((jahr - erstes) / (letztes - erstes)) * (B - L - R);
    const y = (wert) => O + (1 - (wert - min) / (max - min)) * (H - O - U);
    const tausend = (wert) => (Math.abs(wert) >= 1e6 ? `${kurz.format(wert / 1e6)} Mio.` : `${kurz.format(wert / 1e3)}k`);

    let achsen = "";
    for (let w = min; w <= max + schritt / 2; w += schritt) {
      achsen += `<line class="${w === 0 ? "null" : "gitter"}" x1="${L}" x2="${B - R}" y1="${y(w)}" y2="${y(w)}"></line>
        <text class="ylabel" x="${L - 6}" y="${y(w) + 3.5}">${tausend(w)}</text>`;
    }
    const xSchritt = letztes - erstes > 30 ? 10 : 5;
    for (let j = Math.ceil(erstes / xSchritt) * xSchritt; j <= letztes; j += xSchritt) {
      achsen += `<text class="xlabel" x="${x(j)}" y="${H - 6}">${j}</text>`;
    }
    const marken = [
      ["Pension Er", state.attributes.pension_er],
      ["Pension Sie", state.attributes.pension_sie],
    ]
      .filter(([, jahr]) => jahr >= erstes && jahr <= letztes)
      .map(
        ([name, jahr], i) => `<line class="marke" x1="${x(jahr)}" x2="${x(jahr)}" y1="${O}" y2="${H - U}"></line>
          <text class="markenlabel" x="${x(jahr) + 3}" y="${O + 9 + i * 11}">${name}</text>`,
      )
      .join("");
    const linien = reihen
      .map((r) => {
        const punkte = jahre.map((j) => `${x(j.jahr).toFixed(1)},${y(Number(j[r.schluessel]) || 0).toFixed(1)}`);
        return `<polyline class="linie" stroke="${escape(r.farbe)}" points="${punkte.join(" ")}"></polyline>`;
      })
      .join("");
    const legende = reihen
      .map((r) => `<li><span class="strich" style="background:${escape(r.farbe)}"></span>${escape(r.name)}</li>`)
      .join("");

    this.shadowRoot.innerHTML = `
      <style>
        ha-card { padding: 16px; position: relative; }
        .titel { margin: 0 0 8px; font-size: 16px; font-weight: 500; color: var(--primary-text-color); }
        svg { display: block; width: 100%; height: auto; touch-action: pan-y; }
        text { fill: var(--secondary-text-color); font-size: 10px; font-variant-numeric: tabular-nums; }
        .ylabel { text-anchor: end; }
        .xlabel { text-anchor: middle; }
        .gitter { stroke: var(--divider-color, #e0e0e0); stroke-width: 0.5; }
        .null { stroke: var(--secondary-text-color); stroke-width: 0.8; }
        .marke { stroke: var(--secondary-text-color); stroke-width: 0.8; stroke-dasharray: 3 3; }
        .markenlabel { font-size: 9px; }
        .linie { fill: none; stroke-width: 2; stroke-linejoin: round; }
        .zeiger { stroke: var(--primary-text-color); stroke-width: 0.6; visibility: hidden; }
        .legende { display: flex; flex-wrap: wrap; gap: 4px 16px; list-style: none; margin: 8px 0 0; padding: 0;
          color: var(--primary-text-color); font-size: 13px; }
        .strich { display: inline-block; width: 14px; height: 3px; border-radius: 2px; margin-right: 6px; vertical-align: middle; }
        .tipp { position: absolute; pointer-events: none; visibility: hidden; background: var(--card-background-color, #fff);
          border: 1px solid var(--divider-color, #e0e0e0); border-radius: 8px; padding: 6px 8px; font-size: 12px;
          color: var(--primary-text-color); box-shadow: 0 2px 6px rgba(0,0,0,.15); white-space: nowrap; }
        .tipp b { display: block; margin-bottom: 2px; }
        .tipp span { font-variant-numeric: tabular-nums; }
      </style>
      <ha-card>${titel}
        <svg viewBox="0 0 ${B} ${H}" role="img" aria-label="${escape(this._config.title ?? "Verlauf")}">
          ${achsen}${marken}${linien}
          <line class="zeiger" y1="${O}" y2="${H - U}"></line>
          <rect class="flaeche" x="${L}" y="${O}" width="${B - L - R}" height="${H - O - U}" fill="transparent"></rect>
        </svg>
        <ul class="legende">${legende}</ul>
        <div class="tipp"></div>
      </ha-card>`;

    const svg = this.shadowRoot.querySelector("svg");
    const zeiger = this.shadowRoot.querySelector(".zeiger");
    const tipp = this.shadowRoot.querySelector(".tipp");
    const flaeche = this.shadowRoot.querySelector(".flaeche");
    if (!svg?.getBoundingClientRect || !flaeche) return;
    flaeche.addEventListener("pointermove", (ev) => {
      const box = svg.getBoundingClientRect();
      const svgX = ((ev.clientX - box.left) / box.width) * B;
      const index = Math.round(((svgX - L) / (B - L - R)) * (letztes - erstes));
      const j = jahre[Math.min(Math.max(index, 0), jahre.length - 1)];
      zeiger.setAttribute("x1", x(j.jahr));
      zeiger.setAttribute("x2", x(j.jahr));
      zeiger.style.visibility = "visible";
      tipp.innerHTML = `<b>${j.jahr}</b>${reihen
        .map((r) => `<div><span style="color:${escape(r.farbe)}">●</span> ${escape(r.name)}: <span>${zahl.format(j[r.schluessel])}</span></div>`)
        .join("")}`;
      const links = (x(j.jahr) / B) * box.width + 16;
      tipp.style.left = `${Math.min(links + 8, box.width - tipp.offsetWidth + 16)}px`;
      tipp.style.top = "48px";
      tipp.style.visibility = "visible";
    });
    flaeche.addEventListener("pointerleave", () => {
      zeiger.style.visibility = "hidden";
      tipp.style.visibility = "hidden";
    });
  }
}

// Ansicht «Vorsorge», nur wenn simulation.yaml vorhanden ist
function vorsorgeAnsicht(vorhanden) {
  const regler = REGLER.map((r) => `number.${SIM}${r}`).filter((id) => vorhanden.has(id));
  const kennzahlen = KENNZAHLEN.map((k) => `sensor.${SIM}${k}`).filter((id) => vorhanden.has(id));
  return {
    title: "Vorsorge",
    path: "vorsorge",
    icon: "mdi:account-clock",
    type: "sections",
    max_columns: 2,
    sections: [
      {
        type: "grid",
        cards: [
          { type: "heading", heading: "Szenario", icon: "mdi:directions-fork" },
          {
            type: "entities",
            entities: [`select.${SIM}szenario`, ...regler, `button.${SIM}zuruecksetzen`],
          },
        ],
      },
      {
        type: "grid",
        cards: [
          { type: "heading", heading: "Kennzahlen", icon: "mdi:clipboard-text-outline" },
          { type: "markdown", content: WARNUNGEN },
          ...kennzahlen.map((entity) => ({ type: "tile", entity, grid_options: { columns: 6 } })),
        ],
      },
      {
        type: "grid",
        column_span: 2,
        cards: [
          { type: "heading", heading: "Verlauf (heutige CHF)", icon: "mdi:chart-line" },
          {
            type: "custom:finanzcockpit-verlauf-card",
            title: "Vermögen und Hypothek",
            entity: VERLAUF,
            reihen: ["frei_real", "nettovermoegen_real", "hypothek_real"],
          },
          {
            type: "custom:finanzcockpit-verlauf-card",
            title: "Renten und Ausgaben pro Jahr",
            entity: VERLAUF,
            reihen: ["renten_real", "ausgaben_real"],
          },
          { type: "heading", heading: "Szenarien im Vergleich", icon: "mdi:compare-horizontal" },
          { type: "markdown", content: VERGLEICHSTABELLE },
        ],
      },
    ],
  };
}

// Erzeugt die Dashboard-Konfiguration aus den vorhandenen Sensoren
export function erzeugeDashboard(hass) {
  const eigene = Object.keys(hass.states).filter((id) =>
    hass.entities?.[id] ? hass.entities[id].platform === PLATTFORM : id.split(".")[1].startsWith(`${PLATTFORM}_`),
  );
  const vorhanden = new Set(eigene);

  const waehrungen = eigene
    .filter((id) => id.startsWith(`${SUMME}waehrung_`))
    .sort()
    .map((id) => {
      const code = id.slice(`${SUMME}waehrung_`.length);
      return { entity: id, name: code.toUpperCase(), color: WAEHRUNGSFARBEN[code] };
    });
  const anlageklassen = ANLAGEKLASSEN.filter(([klasse]) =>
    vorhanden.has(`${SUMME}anlageklasse_${klasse}`),
  ).map(([klasse, name, color]) => ({ entity: `${SUMME}anlageklasse_${klasse}`, name, color }));

  const vermoegen = [{ type: "heading", heading: "Vermögen", icon: "mdi:bank" }];
  if (vorhanden.has(`${SUMME}total`)) {
    vermoegen.push({
      type: "tile",
      entity: `${SUMME}total`,
      name: "Total",
      grid_options: { columns: 12 },
    });
  }
  vermoegen.push(
    { type: "custom:finanzcockpit-donut-card", title: "Währungen (in CHF)", entities: waehrungen },
    { type: "custom:finanzcockpit-donut-card", title: "Anlageklassen", entities: anlageklassen },
  );

  return {
    title: "Finanzen",
    views: [
      {
        title: "Übersicht",
        path: "uebersicht",
        icon: "mdi:finance",
        type: "sections",
        max_columns: 2,
        sections: [
          { type: "grid", cards: vermoegen },
          {
            type: "grid",
            cards: [
              { type: "heading", heading: "Konten", icon: "mdi:format-list-bulleted" },
              { type: "markdown", content: KONTENTABELLE },
            ],
          },
        ],
      },
      ...(vorhanden.has(VERLAUF) ? [vorsorgeAnsicht(vorhanden)] : []),
    ],
  };
}

class FinanzcockpitDashboardStrategy extends HTMLElement {
  static async generate(config, hass) {
    return erzeugeDashboard(hass);
  }
}

// Mehrfaches Laden (z.B. nach einem Update ohne Neustart des Browsers) ist erlaubt
const definiere = (name, klasse) => customElements.get(name) || customElements.define(name, klasse);
definiere("finanzcockpit-donut-card", FinanzcockpitDonutCard);
definiere("finanzcockpit-verlauf-card", FinanzcockpitVerlaufCard);
definiere("ll-strategy-dashboard-finanzcockpit", FinanzcockpitDashboardStrategy);

window.customCards = window.customCards || [];
for (const karte of [
  {
    type: "finanzcockpit-donut-card",
    name: "Finanzcockpit Kuchendiagramm",
    description: "Zeigt die Aufteilung mehrerer Sensoren als Donut mit Legende und Total.",
  },
  {
    type: "finanzcockpit-verlauf-card",
    name: "Finanzcockpit Vorsorge-Verlauf",
    description: "Zeigt die Jahreswerte der Vorsorge-Simulation als Liniendiagramm.",
  },
]) {
  if (!window.customCards.some((k) => k.type === karte.type)) window.customCards.push(karte);
}
