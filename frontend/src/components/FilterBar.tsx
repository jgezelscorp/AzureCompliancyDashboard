import type { FilterKey, FilterOption, Filters, FilterOptions } from "../api/policyTypes";

interface Field {
  key: FilterKey;
  label: string;
  option: string;
  /** Value stored in the URL for an option; resource groups are filtered by name. */
  value: (o: FilterOption) => string;
}

const FIELDS: Field[] = [
  { key: "sub", label: "Subscription", option: "subscription", value: (o) => o.key },
  { key: "rg", label: "Resource group", option: "resourceGroup", value: (o) => o.label },
  { key: "loc", label: "Location", option: "location", value: (o) => o.key },
  { key: "rtype", label: "Resource type", option: "resourceType", value: (o) => o.key },
  { key: "initiative", label: "Initiative", option: "initiative", value: (o) => o.key },
  { key: "assignment", label: "Assignment", option: "assignment", value: (o) => o.key },
  { key: "state", label: "State", option: "state", value: (o) => o.key },
  { key: "category", label: "Category", option: "category", value: (o) => o.key },
  { key: "effect", label: "Effect", option: "effect", value: (o) => o.key },
  { key: "severity", label: "Severity", option: "severity", value: (o) => o.key },
];

const FRESHNESS = [
  { value: "", label: "Any age" },
  { value: "max:24", label: "Evaluated in the last 24 h" },
  { value: "min:24", label: "Older than 24 h (stale)" },
  { value: "min:168", label: "Older than 7 days" },
];

function optionsFor(opts: FilterOptions | null, name: string): FilterOption[] {
  const v = opts?.options[name];
  return Array.isArray(v) ? (v.filter((x) => typeof x !== "string") as FilterOption[]) : [];
}

export function activeCount(f: Filters): number {
  return Object.values(f).reduce((n, v) => n + (v?.length ?? 0), 0);
}

export function FilterBar({
  filters,
  options,
  onChange,
}: {
  filters: Filters;
  options: FilterOptions | null;
  onChange: (next: Filters) => void;
}) {
  const set = (key: FilterKey, values: string[]) => {
    const next = { ...filters };
    if (values.length) next[key] = values;
    else delete next[key];
    onChange(next);
  };
  const tagKeys = (options?.options.tagKeys ?? []) as string[];
  const freshness = filters.maxAgeHours?.[0] ? `max:${filters.maxAgeHours[0]}` : filters.minAgeHours?.[0] ? `min:${filters.minAgeHours[0]}` : "";
  const chips = Object.entries(filters).flatMap(([k, values]) => (values ?? []).map((v) => ({ k: k as FilterKey, v })));
  return (
    <form className="filter-bar no-print" role="search" aria-label="Filters" onSubmit={(e) => e.preventDefault()}>
      <label>
        Search
        <input
          type="search"
          value={filters.q?.[0] ?? ""}
          placeholder="resource, policy, assignment"
          onChange={(e) => set("q", e.target.value ? [e.target.value] : [])}
        />
      </label>
      {FIELDS.map((f) => {
        const list = optionsFor(options, f.option);
        if (list.length === 0) return null;
        return (
          <label key={f.key}>
            {f.label}
            <select value="" onChange={(e) => e.target.value && set(f.key, [...(filters[f.key] ?? []), e.target.value])}>
              <option value="">Add…</option>
              {list.slice(0, 200).map((o) => (
                <option key={o.key} value={f.value(o)}>
                  {o.label} ({o.evaluations})
                </option>
              ))}
            </select>
          </label>
        );
      })}
      {tagKeys.length > 0 && (
        <label>
          Tag (key:value)
          <input
            type="text"
            list="tag-keys"
            placeholder={`${tagKeys[0]}:value`}
            onKeyDown={(e) => {
              const el = e.currentTarget;
              if (e.key === "Enter" && /^[^:]+:.+$/.test(el.value)) {
                set("tag", [...(filters.tag ?? []), el.value]);
                el.value = "";
              }
            }}
          />
          <datalist id="tag-keys">{tagKeys.map((k) => <option key={k} value={`${k}:`} />)}</datalist>
        </label>
      )}
      <label>
        Freshness
        <select
          value={freshness}
          onChange={(e) => {
            const next = { ...filters };
            delete next.maxAgeHours;
            delete next.minAgeHours;
            const [kind, hours] = e.target.value.split(":");
            if (kind === "max") next.maxAgeHours = [hours];
            if (kind === "min") next.minAgeHours = [hours];
            onChange(next);
          }}
        >
          {FRESHNESS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
        </select>
      </label>
      {chips.length > 0 && (
        <ul className="chips" aria-label="Active filters">
          {chips.filter((c) => c.k !== "q").map((c) => (
            <li key={`${c.k}=${c.v}`}>
              <button type="button" className="chip" onClick={() => set(c.k, (filters[c.k] ?? []).filter((x) => x !== c.v))} aria-label={`Remove filter ${c.k} ${c.v}`}>
                {c.k}: {c.v.length > 40 ? `…${c.v.slice(-38)}` : c.v} ✕
              </button>
            </li>
          ))}
          <li><button type="button" className="link-btn" onClick={() => onChange({})}>Clear all</button></li>
        </ul>
      )}
    </form>
  );
}
