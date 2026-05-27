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

export default function Home() {
  const [commanders, setCommanders] = useState<Commander[]>([]);
  const [filter, setFilter] = useState("");
  const [selectedSlug, setSelectedSlug] = useState("");
  const [bracket, setBracket] = useState(4);
  const [archetype, setArchetype] = useState("");
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

  const filteredCommanders = useMemo(() => {
    if (!filter.trim()) return commanders;
    const f = filter.toLowerCase();
    return commanders.filter((c) => c.name.toLowerCase().includes(f));
  }, [commanders, filter]);

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
    <main className="mx-auto max-w-4xl p-6 md:p-8">
      <header className="mb-8">
        <h1 className="text-3xl font-bold tracking-tight">Deckbuilder</h1>
        <p className="text-sm text-zinc-500 dark:text-zinc-400">
          Commander deck assembly · {commanders.length} commanders available
        </p>
      </header>

      <section className="mb-6 rounded-lg border border-zinc-200 bg-zinc-50 p-5 dark:border-zinc-800 dark:bg-zinc-900">
        <div className="mb-4">
          <label className="mb-1 block text-sm font-medium">
            Filter commanders
            {filter && (
              <span className="ml-2 text-xs text-zinc-500">
                {filteredCommanders.length} match
              </span>
            )}
          </label>
          <input
            type="text"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            placeholder="Type to filter (e.g. 'atraxa')…"
            className="w-full rounded-md border border-zinc-300 bg-white px-3 py-2 text-sm dark:border-zinc-700 dark:bg-zinc-800"
          />
        </div>

        <div className="mb-4">
          <label className="mb-1 block text-sm font-medium">Commander</label>
          <select
            value={selectedSlug}
            onChange={(e) => setSelectedSlug(e.target.value)}
            className="w-full rounded-md border border-zinc-300 bg-white px-3 py-2 text-sm dark:border-zinc-700 dark:bg-zinc-800"
          >
            <option value="">— pick one —</option>
            {filteredCommanders.map((c) => (
              <option key={c.slug} value={c.slug}>
                {c.name} ({c.color_identity.join("") || "C"}) —{" "}
                {c.deck_count.toLocaleString()} decks
              </option>
            ))}
          </select>
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
              Archetype <span className="text-zinc-500">(optional)</span>
            </label>
            <input
              type="text"
              value={archetype}
              onChange={(e) => setArchetype(e.target.value)}
              placeholder="e.g. infect, lands-matter, voltron"
              className="w-full rounded-md border border-zinc-300 bg-white px-3 py-2 text-sm dark:border-zinc-700 dark:bg-zinc-800"
            />
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

      {error && (
        <div className="mb-6 rounded-md border border-red-200 bg-red-50 p-4 text-sm text-red-800 dark:border-red-900 dark:bg-red-950 dark:text-red-300">
          {error}
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
        {card.mana_cost && (
          <span className="ml-2 text-xs text-zinc-500">{card.mana_cost}</span>
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
