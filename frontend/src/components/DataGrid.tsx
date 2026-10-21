import type { ReactNode } from "react";

export interface Column<T> {
  id: string;
  header: string;
  render: (row: T) => ReactNode;
  /** Server sort key; omit for columns the API cannot sort. */
  sort?: string;
  numeric?: boolean;
  rowHeader?: boolean;
}

export function DataGrid<T>({
  caption,
  columns,
  rows,
  rowKey,
  sort,
  desc,
  onSort,
  total,
  offset,
  limit,
  onPage,
}: {
  caption: string;
  columns: Column<T>[];
  rows: T[];
  rowKey: (row: T) => string;
  sort?: string;
  desc?: boolean;
  onSort?: (sort: string, desc: boolean) => void;
  total: number;
  offset: number;
  limit: number;
  onPage: (offset: number) => void;
}) {
  const from = total === 0 ? 0 : offset + 1;
  const to = Math.min(total, offset + rows.length);
  return (
    <div className="grid-wrap">
      <div className="table-scroll" tabIndex={0} role="region" aria-label={`${caption} (scrollable)`}>
        <table className="data-table">
          <caption className="sr-only">{caption}</caption>
          <thead>
            <tr>
              {columns.map((c) => {
                const active = c.sort !== undefined && c.sort === sort;
                return (
                  <th
                    key={c.id}
                    scope="col"
                    className={c.numeric ? "num" : undefined}
                    aria-sort={active ? (desc ? "descending" : "ascending") : undefined}
                  >
                    {c.sort && onSort ? (
                      <button type="button" className="sort-btn" onClick={() => onSort(c.sort as string, active ? !desc : true)}>
                        {c.header}
                        <span aria-hidden="true">{active ? (desc ? " ▼" : " ▲") : ""}</span>
                      </button>
                    ) : (
                      c.header
                    )}
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={rowKey(r)}>
                {columns.map((c) =>
                  c.rowHeader ? (
                    <th scope="row" key={c.id}>{c.render(r)}</th>
                  ) : (
                    <td key={c.id} className={c.numeric ? "num" : undefined}>{c.render(r)}</td>
                  ),
                )}
              </tr>
            ))}
            {rows.length === 0 && (
              <tr><td colSpan={columns.length}>No rows match the current filters.</td></tr>
            )}
          </tbody>
        </table>
      </div>
      <nav className="pager no-print" aria-label={`${caption} pages`}>
        <span aria-live="polite">{from.toLocaleString("en")}–{to.toLocaleString("en")} of {total.toLocaleString("en")} rows</span>
        <button type="button" className="btn" disabled={offset === 0} onClick={() => onPage(Math.max(0, offset - limit))}>Previous</button>
        <button type="button" className="btn" disabled={offset + limit >= total} onClick={() => onPage(offset + limit)}>Next</button>
      </nav>
    </div>
  );
}
