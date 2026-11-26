import { useEffect, useRef, useState } from "react";
import { Search } from "lucide-react";
import { api, type Person } from "@/api/client";
import { StatusBadge } from "./ui/StatusBadge";

type Props = {
  selected: Person | null;
  onSelect: (p: Person) => void;
};

export function PersonPicker({ selected, onSelect }: Props) {
  const [q, setQ] = useState("");
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<Person[]>([]);
  const [loading, setLoading] = useState(false);
  const wrap = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const onDoc = (e: MouseEvent) => {
      if (!wrap.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("click", onDoc);
    return () => document.removeEventListener("click", onDoc);
  }, []);

  useEffect(() => {
    if (!q.trim()) {
      setItems([]);
      setOpen(false);
      return;
    }
    const t = window.setTimeout(async () => {
      setLoading(true);
      try {
        const r = await api.searchPersons(q.trim());
        setItems(r.items || []);
        setOpen(true);
      } catch {
        setItems([]);
        setOpen(true);
      } finally {
        setLoading(false);
      }
    }, 220);
    return () => window.clearTimeout(t);
  }, [q]);

  return (
    <div className="card">
      <label className="field" htmlFor="personQ">
        选人（姓名 / 学号 / user_id）
      </label>
      <div className="picker" ref={wrap}>
        <div style={{ position: "relative" }}>
          <Search
            size={16}
            style={{ position: "absolute", left: 12, top: 13, color: "var(--muted)" }}
          />
          <input
            id="personQ"
            className="input"
            style={{ paddingLeft: 36 }}
            type="search"
            placeholder="输入即搜 · 本地底库 + 云端反查"
            autoComplete="off"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            onFocus={() => items.length && setOpen(true)}
          />
        </div>
        {open ? (
          <div className="suggest" role="listbox">
            {loading ? (
              <button type="button" disabled>
                搜索中…
              </button>
            ) : items.length === 0 ? (
              <button type="button" disabled>
                无匹配 · 可输入纯数字 user_id
              </button>
            ) : (
              items.map((p) => (
                <button
                  key={`${p.source || "x"}-${p.user_id}`}
                  type="button"
                  onClick={() => {
                    onSelect(p);
                    setQ(p.display_name ? `${p.display_name} · ${p.user_id}` : p.user_id);
                    setOpen(false);
                  }}
                >
                  <span style={{ flex: 1 }}>
                    <b>{p.display_name || "（无姓名）"}</b>
                    <br />
                    <span className="meta">
                      {p.user_id}
                      {p.source ? ` · ${p.source}` : ""}
                    </span>
                  </span>
                  <StatusBadge status={p.face_status} />
                </button>
              ))
            )}
          </div>
        ) : null}
      </div>
      {selected ? (
        <div className="picked">
          <div>
            <div style={{ fontWeight: 600 }}>{selected.display_name || "未命名学员"}</div>
            <div className="sub">user_id {selected.user_id}</div>
          </div>
          <StatusBadge status={selected.face_status} />
        </div>
      ) : null}
    </div>
  );
}
