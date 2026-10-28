// Tests für das Frontend: node --test tests/js
import assert from "node:assert/strict";
import { test } from "node:test";

// Minimale Browser-Umgebung
const elemente = new Map();
globalThis.window = globalThis;
globalThis.HTMLElement = class {
  attachShadow() {
    this.shadowRoot = { innerHTML: "", querySelector: () => null, querySelectorAll: () => [] };
    return this.shadowRoot;
  }
};
globalThis.customElements = {
  get: (name) => elemente.get(name),
  define: (name, klasse) => elemente.set(name, klasse),
};

const { erzeugeDashboard, gruppiereKonten } = await import(
  "../../custom_components/finanzcockpit/frontend/finanzcockpit.js"
);

const sensor = (state, unit = "CHF") => ({ state: String(state), attributes: { unit_of_measurement: unit } });
const hass = {
  locale: { language: "de-CH" },
  states: {
    "sensor.finanzcockpit_lohnkonto": sensor(11805.4),
    "sensor.finanzcockpit_summe_total": sensor(30000),
    "sensor.finanzcockpit_summe_waehrung_chf": sensor(20000),
    "sensor.finanzcockpit_summe_waehrung_eur": sensor(10000),
    "sensor.finanzcockpit_summe_anlageklasse_aktien": sensor(10000),
    "sensor.finanzcockpit_summe_anlageklasse_liquiditaet": sensor(20000),
    "sensor.fremd_summe_total": sensor(1),
  },
  entities: {
    "sensor.finanzcockpit_lohnkonto": { platform: "finanzcockpit" },
    "sensor.finanzcockpit_summe_total": { platform: "finanzcockpit" },
    "sensor.finanzcockpit_summe_waehrung_chf": { platform: "finanzcockpit" },
    "sensor.finanzcockpit_summe_waehrung_eur": { platform: "finanzcockpit" },
    "sensor.finanzcockpit_summe_anlageklasse_aktien": { platform: "finanzcockpit" },
    "sensor.finanzcockpit_summe_anlageklasse_liquiditaet": { platform: "finanzcockpit" },
    "sensor.fremd_summe_total": { platform: "andere" },
  },
};

test("Elemente sind registriert", () => {
  assert.ok(elemente.has("finanzcockpit-donut-card"));
  assert.ok(elemente.has("finanzcockpit-verlauf-card"));
  assert.ok(elemente.has("finanzcockpit-balken-card"));
  assert.ok(elemente.has("ll-strategy-dashboard-finanzcockpit"));
  assert.deepEqual(
    window.customCards.map((k) => k.type),
    ["finanzcockpit-donut-card", "finanzcockpit-balken-card", "finanzcockpit-verlauf-card"],
  );
});

test("Strategie erzeugt das Dashboard aus den vorhandenen Sensoren", async () => {
  const strategie = elemente.get("ll-strategy-dashboard-finanzcockpit");
  const dashboard = await strategie.generate({}, hass);
  const karten = dashboard.views[0].sections.flatMap((s) => s.cards);
  const donuts = karten.filter((k) => k.type === "custom:finanzcockpit-donut-card");

  assert.deepEqual(
    donuts[0].entities.map((e) => e.name),
    ["CHF", "EUR"],
  );
  // Reihenfolge der Anlageklassen ist fest, fehlende Klassen fallen weg
  assert.deepEqual(
    donuts[1].entities.map((e) => e.name),
    ["Liquidität", "Aktien"],
  );
  assert.ok(karten.some((k) => k.type === "tile" && k.entity === "sensor.finanzcockpit_summe_total"));
  assert.match(karten.find((k) => k.type === "markdown").content, /integration_entities\('finanzcockpit'\)/);
  // Ohne simulation.yaml gibt es keine Ansicht «Vorsorge»
  assert.equal(dashboard.views.length, 1);
});

const jahre = [2027, 2028, 2029, 2030].map((jahr, i) => ({
  jahr,
  frei_real: 100000 - i * 60000,
  hypothek_real: 400000,
  renten_real: 0,
  ausgaben_real: 50000,
}));
const sim = {
  ...hass,
  states: {
    ...hass.states,
    "sensor.finanzcockpit_sim_verlauf": {
      state: "Teilzeit",
      attributes: { jahre, pension_er: 2029, pension_sie: 2040 },
    },
    "select.finanzcockpit_sim_szenario": sensor("Teilzeit", undefined),
    "number.finanzcockpit_sim_pension_er": sensor(2029, undefined),
    "number.finanzcockpit_sim_pensum_er": sensor(80, "%"),
    "button.finanzcockpit_sim_zuruecksetzen": sensor("unknown", undefined),
    "sensor.finanzcockpit_sim_vorsorgeluecke": sensor(500),
    "sensor.finanzcockpit_sim_tragbarkeit": sensor(30, "%"),
  },
  // Ohne Entity-Registry entscheidet das Präfix
  entities: undefined,
};

test("Mit Simulation gibt es die Ansicht «Vorsorge»", async () => {
  const strategie = elemente.get("ll-strategy-dashboard-finanzcockpit");
  const dashboard = await strategie.generate({}, sim);
  const vorsorge = dashboard.views[1];

  assert.equal(vorsorge.path, "vorsorge");
  const karten = vorsorge.sections.flatMap((s) => s.cards);
  // Regler in der Reihenfolge von simulation.py, nur vorhandene
  assert.deepEqual(karten.find((k) => k.type === "entities").entities, [
    "select.finanzcockpit_sim_szenario",
    "number.finanzcockpit_sim_pension_er",
    "number.finanzcockpit_sim_pensum_er",
    "button.finanzcockpit_sim_zuruecksetzen",
  ]);
  assert.deepEqual(
    karten.filter((k) => k.type === "tile").map((k) => k.entity),
    ["sensor.finanzcockpit_sim_vorsorgeluecke", "sensor.finanzcockpit_sim_tragbarkeit"],
  );
  assert.equal(karten.filter((k) => k.type === "custom:finanzcockpit-verlauf-card").length, 2);
  assert.ok(karten.some((k) => k.type === "markdown" && k.content.includes("finanzcockpit_sim_vergleich")));
  assert.ok(!karten.some((k) => k.type === "markdown" && k.content.includes("${")));
});

test("Verlauf zeichnet Linien, Nulllinie und Pensionsmarken", () => {
  const Karte = elemente.get("finanzcockpit-verlauf-card");
  const karte = new Karte();
  karte.setConfig({ title: "Vermögen", entity: "sensor.finanzcockpit_sim_verlauf" });
  karte.hass = sim;
  const html = karte.shadowRoot.innerHTML;

  assert.equal((html.match(/class="linie"/g) ?? []).length, 2);
  assert.match(html, /Freies Vermögen/);
  assert.match(html, /Hypothek/);
  // Negative Werte: die Nulllinie ist sichtbar
  assert.match(html, /class="null"/);
  // Nur die Pension im dargestellten Zeitraum erhält eine Marke
  assert.match(html, />Pension Er</);
  assert.doesNotMatch(html, />Pension Sie</);
});

test("Verlauf ohne Jahreswerte zeigt einen Hinweis", () => {
  const Karte = elemente.get("finanzcockpit-verlauf-card");
  const karte = new Karte();
  karte.setConfig({ entity: "sensor.fehlt", reihen: [{ schluessel: "x", name: "X", color: "#000" }] });
  karte.hass = sim;

  assert.match(karte.shadowRoot.innerHTML, /Keine Werte vorhanden/);
  assert.throws(() => new Karte().setConfig({}), /'entity'/);
});

test("Donut zeigt Anteile, Total und lässt leere Werte weg", () => {
  const Karte = elemente.get("finanzcockpit-donut-card");
  const karte = new Karte();
  karte.setConfig({
    title: "Test <b>",
    entities: [
      { entity: "sensor.finanzcockpit_summe_waehrung_chf", name: "CHF", color: "#D9534F" },
      "sensor.finanzcockpit_summe_waehrung_eur",
      "sensor.fehlt",
    ],
  });
  karte.hass = hass;
  const html = karte.shadowRoot.innerHTML;

  assert.equal((html.match(/class="bogen"/g) ?? []).length, 2);
  // Zahlenformat je nach Umgebung mit ' oder ’ als Tausendertrennzeichen
  assert.ok(html.includes(new Intl.NumberFormat("de-CH").format(30000)));
  assert.match(html, /66[.,]7 %/);
  assert.match(html, /Test &lt;b&gt;/);
});

test("Ohne Werte erscheint ein Hinweis", () => {
  const Karte = elemente.get("finanzcockpit-donut-card");
  const karte = new Karte();
  karte.setConfig({ entities: ["sensor.fehlt"] });
  karte.hass = hass;

  assert.match(karte.shadowRoot.innerHTML, /Keine Werte vorhanden/);
});

test("Konfiguration ohne Sensoren ist ein Fehler", () => {
  const Karte = elemente.get("finanzcockpit-donut-card");
  assert.throws(() => new Karte().setConfig({}), /'entities'/);
});

const konten = {
  ...hass,
  states: {
    "sensor.finanzcockpit_lohn": konto("lohn", 80000, "Alltag", "Bank A"),
    "sensor.finanzcockpit_sparen": konto("sparen", 40000, "Reserve", "Bank A"),
    "sensor.finanzcockpit_depot": konto("depot", 50000, "Reserve", "Broker", 10),
    "sensor.finanzcockpit_hypothek": konto("hypothek", -300000, "Haus", "Bank A"),
    "sensor.finanzcockpit_haus": konto("haus", 200000, "Haus", undefined, 0),
    "sensor.finanzcockpit_summe_total": sensor(70000),
    "sensor.fremd_konto": konto("fremd", 1e6, "Alltag", "Bank A"),
  },
  entities: undefined,
};

function konto(konto_id, wert_chf, topf, institut, liquiditaet = 100) {
  return {
    state: String(wert_chf),
    attributes: {
      konto_id,
      friendly_name: konto_id,
      wert_chf,
      topf,
      institut,
      anlageklasse: { Liquidität: liquiditaet, Aktien: 100 - liquiditaet },
    },
  };
}

test("Konten werden nach Attribut gruppiert", () => {
  assert.deepEqual(
    gruppiereKonten(konten, "topf").map((g) => [g.name, g.wert]),
    [["Reserve", 90000], ["Alltag", 80000], ["Haus", -100000]],
  );
  // Nur Guthaben, Konten ohne Institut fallen weg
  const institute = gruppiereKonten(konten, "institut", { nurGuthaben: true });
  assert.deepEqual(
    institute.map((g) => [g.name, g.wert, g.liquiditaet]),
    [["Bank A", 120000, 120000], ["Broker", 50000, 5000]],
  );
});

test("Donut nach Topf zeigt nur Töpfe mit positivem Saldo", () => {
  const Karte = elemente.get("finanzcockpit-donut-card");
  const karte = new Karte();
  karte.setConfig({ title: "Töpfe", gruppieren: "topf" });
  karte.hass = konten;
  const html = karte.shadowRoot.innerHTML;

  assert.equal((html.match(/class="bogen"/g) ?? []).length, 2);
  assert.match(html, /Reserve/);
  // Negative Töpfe stehen im Hinweis statt im Donut
  assert.equal((html.match(/Haus/g) ?? []).length, 1);
  assert.match(html, /class="hinweis">Nicht enthalten: Haus -100/);
  assert.doesNotMatch(html, /data-entity="/);
  assert.throws(() => new Karte().setConfig({ gruppieren: "" }), /'gruppieren'/);
});

test("Balken je Institut mit Grenzlinie", () => {
  const Karte = elemente.get("finanzcockpit-balken-card");
  const karte = new Karte();
  karte.setConfig({ title: "Institute", grenze: 100000 });
  karte.hass = konten;
  const html = karte.shadowRoot.innerHTML;

  assert.equal((html.match(/<li /g) ?? []).length, 2);
  assert.match(html, /class="grenze"/);
  // Bank A liegt mit 120'000 auf Konten über der Grenze
  assert.equal((html.match(/class="wert ueber"/g) ?? []).length, 1);
  assert.throws(() => new Karte().setConfig({ grenze: -1 }), /'grenze'/);
});

test("Dashboard zeigt Töpfe und Institute, wenn Konten vorhanden sind", async () => {
  const strategie = elemente.get("ll-strategy-dashboard-finanzcockpit");
  const karten = (await strategie.generate({}, konten)).views[0].sections.flatMap((s) => s.cards);

  assert.ok(karten.some((k) => k.gruppieren === "topf"));
  assert.ok(karten.some((k) => k.type === "custom:finanzcockpit-balken-card" && k.grenze === 100000));
});
