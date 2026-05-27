"use client";

import { useEffect, useMemo, useRef, useState } from "react";

// ---------- API types (mirror api/main.py responses) ----------

type Commander = {
  oracle_id: string;
  name: string;
  slug: string;
  color_identity: string[];
  deck_count: number;
};

type Theme = {
  slug: string;
  name: string;
  deck_count: number;
};

type Card = {
  oracle_id: string;
  name: string;
  type_line: string;
  mana_cost: string | null;
  cmc: number;
  color_identity: string[];
  image_uri: string | null;
  synergy_score: number | null;
  inclusion_count: number;
  potential_decks: number;
  is_game_changer: boolean;
  is_high_synergy: boolean;
  score: number;
};

type Role = "land" | "ramp" | "draw" | "interaction" | "wincon" | "payoff";

type PackageDetected = {
  name: string;
  triggers: string[];
  partners_in_deck: string[];
};

type Deck = {
  commander: Card;
  selections: { role: Role; card: Card }[];
  basic_lands: Record<string, number>;
  bracket: number;
  archetype: string | null;
  total_cards: number;
  meta: {
    pool_meta: { source: string; pool_size: number; warnings: string[] };
    role_counts: Record<string, number>;
    gc_kept: number;
    gc_cap: number | null;
    basic_count: number;
    packages: PackageDetected[];
    tribe: string | null;
    tribal_dropped: number;
  };
};

const ROLE_ORDER: Role[] = [
  "land",
  "ramp",
  "draw",
  "interaction",
  "wincon",
  "payoff",
];
const ROLE_LABEL: Record<Role, string> = {
  land: "Lands",
  ramp: "Ramp",
  draw: "Card Draw",
  interaction: "Interaction",
  wincon: "Wincons",
  payoff: "Payoffs / Utility",
};

// ---------- Page ----------

// Read initial form state from the URL so shared links pre-populate.
// Lazy initializer runs on the first render only.
function readInitialUrlState() {
  if (typeof window === "undefined") {
    return { slug: "", bracket: 4, archetype: "" };
  }
  const p = new URLSearchParams(window.location.search);
  const bracketParam = parseInt(p.get("bracket") || "4", 10);
  return {
    slug: p.get("commander") || "",
    bracket: [1, 2, 3, 4].includes(bracketParam) ? bracketParam : 4,
    archetype: p.get("archetype") || "",
  };
}

export default function Home() {
  const initialUrl = useMemo(readInitialUrlState, []);
  const [commanders, setCommanders] = useState<Commander[]>([]);
  const [selectedSlug, setSelectedSlug] = useState(initialUrl.slug);
  const [bracket, setBracket] = useState(initialUrl.bracket);
  const [archetype, setArchetype] = useState(initialUrl.archetype);
  const autoBuildAttempted = useRef(false);
  const commanderChangeIsUserAction = useRef(false);
  const [themes, setThemes] = useState<Theme[]>([]);
  const [themesLoading, setThemesLoading] = useState(false);
  const [deck, setDeck] = useState<Deck | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch("/api/commanders")
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then(setCommanders)
      .catch((e) =>
        setError(`Couldn't load commanders: ${e.message}. Is the API on :8000?`)
      );
  }, []);

  // Load available themes when commander changes. Reset archetype only
  // when the user actually changed commanders (not when state was
  // initialized from a shared URL with both commander and archetype).
  useEffect(() => {
    if (commanderChangeIsUserAction.current) {
      setArchetype("");
    }
    commanderChangeIsUserAction.current = true;
    if (!selectedSlug) {
      setThemes([]);
      return;
    }
    setThemesLoading(true);
    fetch(`/api/commanders/${selectedSlug}/themes`)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then(setThemes)
      .catch(() => setThemes([]))
      .finally(() => setThemesLoading(false));
  }, [selectedSlug]);

  // Sync state -> URL (replaceState, no nav). Lets users bookmark or
  // share any specific (commander, bracket, archetype) combination.
  useEffect(() => {
    const params = new URLSearchParams();
    if (selectedSlug) params.set("commander", selectedSlug);
    if (bracket !== 4) params.set("bracket", String(bracket));
    if (archetype) params.set("archetype", archetype);
    const qs = params.toString();
    const newUrl = qs ? `?${qs}` : window.location.pathname;
    window.history.replaceState(null, "", newUrl);
  }, [selectedSlug, bracket, archetype]);

  const selectedCommander = commanders.find((c) => c.slug === selectedSlug);

  async function handleSubmit() {
    if (!selectedCommander) {
      setError("Choose a commander first.");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const res = await fetch("/api/build", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          commander: selectedCommander.name,
          bracket,
          archetype: archetype.trim() || null,
        }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || `HTTP ${res.status}`);
      }
      setDeck(await res.json());
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setDeck(null);
    } finally {
      setLoading(false);
    }
  }

  // Auto-build once when commanders finish loading and the URL had a
  // commander slug. Fires at most once per page load.
  useEffect(() => {
    if (autoBuildAttempted.current) return;
    if (commanders.length === 0) return;
    if (!initialUrl.slug) {
      autoBuildAttempted.current = true;
      return;
    }
    if (!commanders.find((c) => c.slug === initialUrl.slug)) {
      autoBuildAttempted.current = true;
      return;
    }
    autoBuildAttempted.current = true;
    handleSubmit();
    // handleSubmit isn't reactive, but we only want this on commanders load.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [commanders]);

  const sectionsByRole = useMemo(() => {
    if (!deck) return null;
    const map: Record<Role, Card[]> = {
      land: [],
      ramp: [],
      draw: [],
      interaction: [],
      wincon: [],
      payoff: [],
    };
    for (const sel of deck.selections) map[sel.role].push(sel.card);
    return map;
  }, [deck]);

  return (
    <main className="mx-auto max-w-6xl p-6 md:p-8">
      <header className="mb-6">
        <h1 className="text-3xl font-bold tracking-tight">Deckbuilder</h1>
        <p className="text-sm text-zinc-500 dark:text-zinc-400">
          Commander deck assembly · {commanders.length} commanders available
        </p>
      </header>

      <div className="grid gap-6 md:grid-cols-[320px,1fr]">
      <section className="self-start rounded-lg border border-zinc-200 bg-zinc-50 p-5 md:sticky md:top-6 dark:border-zinc-800 dark:bg-zinc-900">
        <div className="mb-4">
          <label className="mb-1 block text-sm font-medium">Commander</label>
          <CommanderCombobox
            commanders={commanders}
            value={selectedSlug}
            onChange={setSelectedSlug}
          />
        </div>

        <div className="mb-4 flex flex-wrap gap-6">
          <div>
            <label className="mb-1 block text-sm font-medium">Bracket</label>
            <div className="flex gap-2">
              {[1, 2, 3, 4].map((b) => (
                <button
                  key={b}
                  type="button"
                  onClick={() => setBracket(b)}
                  className={`min-w-[44px] rounded-md border px-4 py-2 text-sm font-medium transition-colors ${
                    bracket === b
                      ? "border-blue-600 bg-blue-600 text-white"
                      : "border-zinc-300 bg-white hover:bg-zinc-100 dark:border-zinc-700 dark:bg-zinc-800 dark:hover:bg-zinc-700"
                  }`}
                >
                  {b}
                </button>
              ))}
            </div>
          </div>

          <div className="flex-1 min-w-[200px]">
            <label className="mb-1 block text-sm font-medium">
              Archetype{" "}
              <span className="text-zinc-500">
                {themesLoading
                  ? "(loading…)"
                  : selectedSlug
                  ? `(${themes.length} available)`
                  : "(pick a commander first)"}
              </span>
            </label>
            <select
              value={archetype}
              onChange={(e) => setArchetype(e.target.value)}
              disabled={!selectedSlug || themesLoading}
              className="w-full rounded-md border border-zinc-300 bg-white px-3 py-2 text-sm disabled:cursor-not-allowed disabled:opacity-50 dark:border-zinc-700 dark:bg-zinc-800"
            >
              <option value="">— no archetype —</option>
              {themes.map((t) => (
                <option key={t.slug} value={t.slug}>
                  {t.name} ({t.deck_count.toLocaleString()} decks)
                </option>
              ))}
            </select>
          </div>
        </div>

        <button
          type="button"
          onClick={handleSubmit}
          disabled={loading || !selectedSlug}
          className="w-full rounded-md bg-blue-600 py-2.5 font-medium text-white transition-colors hover:bg-blue-700 disabled:cursor-not-allowed disabled:bg-zinc-400"
        >
          {loading ? "Building deck…" : "Generate Deck"}
        </button>
      </section>

      <div className="min-w-0">
      {error && (
        <div className="mb-6 rounded-md border border-red-200 bg-red-50 p-4 text-sm text-red-800 dark:border-red-900 dark:bg-red-950 dark:text-red-300">
          {error}
        </div>
      )}

      {!deck && !error && !loading && commanders.length > 0 && (
        <div className="rounded-md border border-dashed border-zinc-300 bg-zinc-50 p-8 text-center text-sm text-zinc-500 dark:border-zinc-700 dark:bg-zinc-900">
          Pick a commander and click Generate Deck.
        </div>
      )}

      {deck && sectionsByRole && (
        <article className="space-y-6">
          <div className="rounded-lg border border-zinc-200 bg-zinc-50 p-4 dark:border-zinc-800 dark:bg-zinc-900">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <h2 className="text-xl font-bold">{deck.commander.name}</h2>
              <div className="flex items-baseline gap-3">
                <div className="text-sm text-zinc-500">
                  Bracket {deck.bracket} · {deck.total_cards} cards
                  {deck.archetype && ` · ${deck.archetype}`}
                  {deck.meta.tribe && ` · ${deck.meta.tribe} tribal`}
                </div>
                <CopyDeckButton deck={deck} />
              </div>
            </div>
            <p className="mt-1 text-xs text-zinc-500">
              {deck.commander.type_line}
            </p>
            {deck.meta.pool_meta.warnings.map((w, i) => (
              <p
                key={i}
                className="mt-2 text-sm text-amber-700 dark:text-amber-400"
              >
                ⚠ {w}
              </p>
            ))}
            {deck.meta.packages.length > 0 && (
              <div className="mt-3 border-t border-zinc-200 pt-3 dark:border-zinc-800">
                <p className="mb-1 text-xs font-medium text-zinc-700 dark:text-zinc-300">
                  Detected combo packages
                </p>
                <ul className="space-y-1 text-xs text-zinc-600 dark:text-zinc-400">
                  {deck.meta.packages.map((p) => (
                    <li key={p.name}>
                      <span className="font-mono">{p.name}</span>:{" "}
                      {p.triggers.join(", ")} →{" "}
                      {p.partners_in_deck.join(", ") || "(no partners in deck)"}
                    </li>
                  ))}
                </ul>
              </div>
            )}
            <div className="mt-3 border-t border-zinc-200 pt-3 dark:border-zinc-800">
              <ManaCurve deck={deck} />
            </div>
          </div>

          {ROLE_ORDER.map((role) => {
            const cards = sectionsByRole[role];
            const isLand = role === "land";
            const basicEntries = isLand
              ? Object.entries(deck.basic_lands).map(([name, count]) => ({
                  name,
                  count,
                }))
              : [];
            const total = cards.length + (isLand ? deck.meta.basic_count : 0);
            if (total === 0) return null;
            return (
              <DeckSection
                key={role}
                title={ROLE_LABEL[role]}
                count={total}
                cards={cards}
                basicLands={basicEntries}
              />
            );
          })}
        </article>
      )}
      </div>
      </div>
    </main>
  );
}

// ---------- DeckSection ----------

function DeckSection({
  title,
  count,
  cards,
  basicLands,
}: {
  title: string;
  count: number;
  cards: Card[];
  basicLands?: { name: string; count: number }[];
}) {
  return (
    <section>
      <h3 className="mb-2 text-lg font-semibold">
        {title}{" "}
        <span className="font-normal text-zinc-500">({count})</span>
      </h3>
      <ul className="divide-y divide-zinc-200 rounded-md border border-zinc-200 bg-white dark:divide-zinc-800 dark:border-zinc-800 dark:bg-zinc-900">
        {cards.map((c) => (
          <CardRow key={c.oracle_id} card={c} />
        ))}
        {basicLands?.map((b) => (
          <li
            key={b.name}
            className="flex items-baseline justify-between px-3 py-2 text-sm text-zinc-600 dark:text-zinc-400"
          >
            <span>{b.name}</span>
            <span className="font-mono text-xs">× {b.count}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}

// ---------- ManaCurve ----------

function ManaCurve({ deck }: { deck: Deck }) {
  // Bucket non-land cards by CMC: 0, 1, 2, 3, 4, 5, 6+.
  const buckets = Array.from({ length: 7 }, () => 0);
  let cmcSum = 0;
  let nonLandCount = 0;
  for (const sel of deck.selections) {
    if (sel.role === "land") continue;
    const bucket = Math.min(6, Math.floor(sel.card.cmc));
    buckets[bucket]++;
    cmcSum += sel.card.cmc;
    nonLandCount++;
  }
  const max = Math.max(...buckets, 1);
  const avgCmc = nonLandCount > 0 ? cmcSum / nonLandCount : 0;

  return (
    <div>
      <div className="mb-1 flex items-baseline justify-between">
        <p className="text-xs font-medium text-zinc-700 dark:text-zinc-300">
          Mana curve · non-land
        </p>
        <p className="text-xs text-zinc-500">avg CMC {avgCmc.toFixed(2)}</p>
      </div>
      <div className="flex h-14 items-end gap-1.5">
        {buckets.map((count, cmc) => (
          <div
            key={cmc}
            className="flex flex-1 flex-col items-center justify-end"
            title={`${count} cards at CMC ${cmc === 6 ? "6+" : cmc}`}
          >
            <span className="text-[10px] leading-tight text-zinc-500">
              {count || ""}
            </span>
            <div
              className="w-full rounded-t bg-blue-500/80 transition-all"
              style={{ height: `${(count / max) * 100}%` }}
            />
          </div>
        ))}
      </div>
      <div className="mt-1 flex gap-1.5">
        {buckets.map((_, cmc) => (
          <div
            key={cmc}
            className="flex-1 text-center text-[10px] text-zinc-500"
          >
            {cmc === 6 ? "6+" : cmc}
          </div>
        ))}
      </div>
    </div>
  );
}

// ---------- CommanderCombobox ----------

function CommanderCombobox({
  commanders,
  value,
  onChange,
}: {
  commanders: Commander[];
  value: string;
  onChange: (slug: string) => void;
}) {
  const selected = commanders.find((c) => c.slug === value);
  const [query, setQuery] = useState(selected?.name ?? "");
  const [open, setOpen] = useState(false);
  const [activeIdx, setActiveIdx] = useState(-1);
  const wrapperRef = useRef<HTMLDivElement>(null);

  // If `value` changes externally (URL load, programmatic clear), reflect it.
  useEffect(() => {
    if (selected) setQuery(selected.name);
    else setQuery("");
  }, [selected?.slug]); // eslint-disable-line react-hooks/exhaustive-deps

  // Close dropdown on outside click.
  useEffect(() => {
    function onDoc(e: MouseEvent) {
      if (!wrapperRef.current) return;
      if (!wrapperRef.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, []);

  const matches = useMemo(() => {
    const exactSelected = selected && query === selected.name;
    if (!query.trim() || exactSelected) return commanders.slice(0, 50);
    const q = query.toLowerCase();
    return commanders.filter((c) => c.name.toLowerCase().includes(q)).slice(0, 50);
  }, [commanders, query, selected]);

  function commit(c: Commander) {
    onChange(c.slug);
    setQuery(c.name);
    setOpen(false);
    setActiveIdx(-1);
  }

  function handleKey(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      if (!open) setOpen(true);
      setActiveIdx((i) => Math.min(matches.length - 1, i + 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActiveIdx((i) => Math.max(0, i - 1));
    } else if (e.key === "Enter") {
      e.preventDefault();
      if (open && activeIdx >= 0 && matches[activeIdx]) commit(matches[activeIdx]);
      else if (open && matches.length === 1) commit(matches[0]);
    } else if (e.key === "Escape") {
      setOpen(false);
      setActiveIdx(-1);
    }
  }

  return (
    <div ref={wrapperRef} className="relative">
      <input
        type="text"
        role="combobox"
        aria-expanded={open}
        aria-controls="commander-listbox"
        value={query}
        onChange={(e) => {
          setQuery(e.target.value);
          setOpen(true);
          setActiveIdx(0);
        }}
        onFocus={() => setOpen(true)}
        onKeyDown={handleKey}
        placeholder={`Search ${commanders.length} commanders…`}
        className="w-full rounded-md border border-zinc-300 bg-white px-3 py-2 text-sm dark:border-zinc-700 dark:bg-zinc-800"
      />
      {selected && query === selected.name && (
        <button
          type="button"
          onClick={() => {
            onChange("");
            setQuery("");
            setOpen(false);
          }}
          className="absolute right-2 top-1/2 -translate-y-1/2 rounded p-1 text-zinc-400 hover:bg-zinc-100 hover:text-zinc-700 dark:hover:bg-zinc-700 dark:hover:text-zinc-200"
          title="Clear"
          aria-label="Clear commander"
        >
          ×
        </button>
      )}
      {open && matches.length > 0 && (
        <ul
          id="commander-listbox"
          role="listbox"
          className="absolute z-40 mt-1 max-h-72 w-full overflow-auto rounded-md border border-zinc-300 bg-white shadow-lg dark:border-zinc-700 dark:bg-zinc-800"
        >
          {matches.map((c, i) => (
            <li
              key={c.slug}
              role="option"
              aria-selected={i === activeIdx}
              onMouseEnter={() => setActiveIdx(i)}
              onMouseDown={(e) => {
                // mousedown fires before blur — prevents focus loss
                e.preventDefault();
                commit(c);
              }}
              className={`flex cursor-pointer items-center justify-between px-3 py-2 text-sm ${
                i === activeIdx
                  ? "bg-blue-50 dark:bg-blue-900/30"
                  : ""
              }`}
            >
              <span className="truncate">
                {c.name}
                <span className="ml-2 text-xs text-zinc-500">
                  ({c.color_identity.join("") || "C"})
                </span>
              </span>
              <span className="ml-3 shrink-0 font-mono text-xs text-zinc-500">
                {c.deck_count.toLocaleString()}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

// ---------- ManaCost ----------

function ManaCost({ cost, size = 14 }: { cost: string | null; size?: number }) {
  if (!cost) return null;
  const tokens = cost.match(/\{[^}]+\}/g);
  if (!tokens) return null;
  return (
    <span className="ml-2 inline-flex items-center gap-px align-text-bottom">
      {tokens.map((tok, i) => {
        // Scryfall slug: strip braces and slashes, uppercase. e.g.
        // {2}->2, {W}->W, {W/U}->WU, {2/W}->2W, {W/P}->WP
        const slug = tok.replace(/[{}/]/g, "").toUpperCase();
        return (
          <img
            key={`${i}-${slug}`}
            src={`https://svgs.scryfall.io/card-symbols/${slug}.svg`}
            alt={tok}
            width={size}
            height={size}
            loading="lazy"
            className="inline-block rounded-full shadow-sm"
          />
        );
      })}
    </span>
  );
}

// ---------- CopyDeckButton ----------

function deckToMoxfieldText(deck: Deck): string {
  const lines: string[] = ["Commander", `1 ${deck.commander.name}`, "", "Deck"];
  for (const sel of deck.selections) {
    lines.push(`1 ${sel.card.name}`);
  }
  for (const [name, count] of Object.entries(deck.basic_lands)) {
    lines.push(`${count} ${name}`);
  }
  return lines.join("\n");
}

function CopyDeckButton({ deck }: { deck: Deck }) {
  const [state, setState] = useState<"idle" | "copied" | "error">("idle");

  async function copy() {
    try {
      await navigator.clipboard.writeText(deckToMoxfieldText(deck));
      setState("copied");
      setTimeout(() => setState("idle"), 2000);
    } catch {
      setState("error");
      setTimeout(() => setState("idle"), 2000);
    }
  }

  const label =
    state === "copied"
      ? "Copied!"
      : state === "error"
      ? "Failed"
      : "Copy decklist";

  return (
    <button
      type="button"
      onClick={copy}
      className="rounded-md border border-zinc-300 bg-white px-3 py-1 text-xs font-medium hover:bg-zinc-100 dark:border-zinc-700 dark:bg-zinc-800 dark:hover:bg-zinc-700"
      title="Copy Moxfield/Archidekt-compatible plain-text decklist"
    >
      {label}
    </button>
  );
}

// ---------- CardRow ----------

function CardRow({ card }: { card: Card }) {
  const [hovered, setHovered] = useState(false);
  const rowRef = useRef<HTMLLIElement>(null);
  const [imagePosition, setImagePosition] = useState<"right" | "left">("right");

  // Pick side at hover time based on available viewport space.
  function handleEnter() {
    setHovered(true);
    if (!rowRef.current || !card.image_uri) return;
    const rect = rowRef.current.getBoundingClientRect();
    const spaceRight = window.innerWidth - rect.right;
    setImagePosition(spaceRight > 280 ? "right" : "left");
  }

  return (
    <li
      ref={rowRef}
      onMouseEnter={handleEnter}
      onMouseLeave={() => setHovered(false)}
      className="relative flex items-baseline justify-between px-3 py-2 text-sm hover:bg-zinc-50 dark:hover:bg-zinc-800/50"
    >
      <span className="flex-1 truncate pr-3">
        {card.name}
        {card.is_game_changer && (
          <span className="ml-2 inline-block rounded bg-purple-100 px-1.5 py-0.5 text-xs font-medium text-purple-800 dark:bg-purple-900 dark:text-purple-300">
            GC
          </span>
        )}
        <ManaCost cost={card.mana_cost} />
        {card.cmc > 0 && !card.mana_cost && (
          <span className="ml-2 text-xs text-zinc-500">cmc {card.cmc}</span>
        )}
      </span>
      {card.synergy_score !== null && (
        <span className="ml-3 shrink-0 font-mono text-xs text-zinc-500">
          syn {card.synergy_score >= 0 ? "+" : ""}
          {card.synergy_score.toFixed(2)} ·{" "}
          {((card.inclusion_count / card.potential_decks) * 100).toFixed(0)}%
        </span>
      )}
      {hovered && card.image_uri && (
        <img
          src={card.image_uri}
          alt={card.name}
          loading="lazy"
          className={`pointer-events-none absolute top-0 z-50 w-64 rounded-xl shadow-2xl ring-1 ring-black/10 ${
            imagePosition === "right" ? "left-full ml-2" : "right-full mr-2"
          }`}
        />
      )}
    </li>
  );
}
