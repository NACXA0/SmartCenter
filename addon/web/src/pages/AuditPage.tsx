import { useCallback, useEffect, useState } from "react";
import * as Select from "@radix-ui/react-select";
import { ChevronDown, RefreshCw } from "lucide-react";
import { api, type AuditRow, type Health } from "@/api/client";
import { useToast } from "@/components/ui/Toast";

export function AuditPage() {
  const toast = useToast();
  const [filter, setFilter] = useState("");
  const [items, setItems] = useState<AuditRow[]>([]);
  const [health, setHealth] = useState<Health | null>(null);

  const load = useCallback(async () => {
    try {
      const [h, a] = await Promise.all([api.health(), api.audit(filter, 80)]);
      setHealth(h);
      setItems(a.items || []);
    } catch (e) {
      toast.push(String(e instanceof Error ? e.message : e));
    }
  }, [filter, toast]);

  useEffect(() => {
    load();
  }, [load]);

  const cards: [string, string, boolean][] = [
    ["嵌入模型", health?.embedder_ready ? "已加载" : "未就绪", !!health?.embedder_ready],
    ["MQTT", health?.mqtt_enabled ? health.mqtt_host || "on" : "关闭（本机开发常见）", !!health?.mqtt_enabled],
    ["磁盘", health?.disk_full ? "空间不足" : "正常", !health?.disk_full],
  ];

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1>审计</h1>
          <p>门口比对流水 · 链路状态</p>
        </div>
        <button type="button" className="btn ghost" onClick={load}>
          <RefreshCw size={16} /> 刷新
        </button>
      </div>

      <div className="status-grid">
        {cards.map(([h, v, good]) => (
          <div className="stat" key={h}>
            <h4>{h}</h4>
            <strong style={{ color: good ? "var(--ok)" : "var(--warn)" }}>{v}</strong>
          </div>
        ))}
      </div>

      <div className="toolbar">
        <Select.Root value={filter || "all"} onValueChange={(v) => setFilter(v === "all" ? "" : v)}>
          <Select.Trigger className="select-trigger btn" aria-label="决策筛选">
            <Select.Value placeholder="全部决策" />
            <Select.Icon>
              <ChevronDown size={16} />
            </Select.Icon>
          </Select.Trigger>
          <Select.Portal>
            <Select.Content className="rdx-content" position="popper" sideOffset={6}>
              <Select.Viewport>
                {[
                  ["all", "全部决策"],
                  ["grant", "开门 grant"],
                  ["deny", "拒绝 deny"],
                  ["skip", "跳过 skip"],
                ].map(([v, label]) => (
                  <Select.Item key={v} value={v} className="rdx-item">
                    <Select.ItemText>{label}</Select.ItemText>
                  </Select.Item>
                ))}
              </Select.Viewport>
            </Select.Content>
          </Select.Portal>
        </Select.Root>
      </div>

      <div className="list">
        {items.length === 0 ? (
          <p className="note">暂无门口比对记录（本机开发且 MQTT off 时常见）</p>
        ) : (
          items.map((a) => {
            const t = a.created_at ? new Date(a.created_at * 1000).toLocaleString() : "";
            const reason = (a.detail && (a.detail.reason as string)) || "";
            return (
              <div className="audit-item" key={a.id}>
                <div>
                  <div style={{ fontWeight: 600 }}>
                    {a.user_id || "—"} · {a.camera || ""}
                  </div>
                  <div className="note">
                    {t}
                    {reason ? ` · ${reason}` : ""}
                    {a.similarity ? ` · sim ${Number(a.similarity).toFixed(3)}` : ""}
                  </div>
                </div>
                <div className={`dec ${a.decision}`}>{a.decision}</div>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}
