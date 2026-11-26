import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { AlertTriangle, DoorOpen, RefreshCw, Users } from "lucide-react";
import { api, type Dashboard } from "@/api/client";
import { STATUS_LABEL } from "@/lib/status";
import { useToast } from "@/components/ui/Toast";

function Bar({ label, value, max, color }: { label: string; value: number; max: number; color: string }) {
  const pct = max > 0 ? Math.max(4, Math.round((value / max) * 100)) : 0;
  return (
    <div className="bar-row">
      <span className="bar-label">{label}</span>
      <div className="bar-track">
        <div className="bar-fill" style={{ width: `${pct}%`, background: color }} />
      </div>
      <span className="bar-val">{value}</span>
    </div>
  );
}

export function OverviewPage() {
  const toast = useToast();
  const navigate = useNavigate();
  const [d, setD] = useState<Dashboard | null>(null);

  const load = useCallback(async () => {
    try {
      setD(await api.stats());
    } catch (e) {
      toast.push(String(e instanceof Error ? e.message : e));
    }
  }, [toast]);

  useEffect(() => {
    load();
    const t = window.setInterval(load, 20000);
    return () => window.clearInterval(t);
  }, [load]);

  const by = d?.persons.by_status || {};
  const statusMax = Math.max(1, ...Object.values(by));
  const h24 = d?.access.h24 || { grant: 0, deny: 0, skip: 0 };
  const d7 = d?.access.d7 || { grant: 0, deny: 0, skip: 0 };
  const accessMax = Math.max(1, h24.grant + h24.deny + h24.skip, d7.grant + d7.deny + d7.skip);
  const pending = d?.persons.pending_recollect || [];
  const dbMb = ((d?.store.db_bytes || 0) / (1024 * 1024)).toFixed(2);

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1>概览</h1>
          <p>本店人脸能力健康度 · 底库与开门统计</p>
        </div>
        <button type="button" className="btn ghost" onClick={load}>
          <RefreshCw size={16} /> 刷新
        </button>
      </div>

      <div className="kpi-grid">
        <div className="kpi">
          <div className="kpi-ico"><Users size={18} /></div>
          <div>
            <div className="kpi-label">人脸库</div>
            <div className="kpi-val">{d?.persons.total ?? "—"}</div>
            <div className="kpi-sub">可开门 {d?.persons.enabled_door ?? 0}</div>
          </div>
        </div>
        <div className="kpi">
          <div className="kpi-ico"><DoorOpen size={18} /></div>
          <div>
            <div className="kpi-label">今日开门</div>
            <div className="kpi-val">{h24.grant}</div>
            <div className="kpi-sub">拒 {h24.deny} · 跳过 {h24.skip}</div>
          </div>
        </div>
        <div className="kpi warn">
          <div className="kpi-ico"><AlertTriangle size={18} /></div>
          <div>
            <div className="kpi-label">待重采</div>
            <div className="kpi-val">{pending.length}</div>
            <div className="kpi-sub">verified 回流 / 未完成</div>
          </div>
        </div>
        <div className="kpi">
          <div className="kpi-label">运行时</div>
          <div className="kpi-sub" style={{ marginTop: 6, lineHeight: 1.6 }}>
            模型 {d?.runtime.embedder_ready ? d.runtime.model_version : "未就绪"}
            <br />
            MQTT {d?.runtime.mqtt_enabled ? d.runtime.mqtt_host : "off"}
            <br />
            库 {dbMb} MB · 审计行 {d?.store.match_audit ?? 0}
          </div>
        </div>
      </div>

      <div className="split-2" style={{ marginTop: 14 }}>
        <div className="card">
          <h3 className="card-title">状态分布</h3>
          {(["pending", "accepted", "verified", "rejected", "none"] as const).map((k) => (
            <Bar
              key={k}
              label={STATUS_LABEL[k] || k}
              value={by[k] || 0}
              max={statusMax}
              color={
                k === "verified" || k === "accepted"
                  ? "var(--ok)"
                  : k === "pending"
                    ? "var(--info)"
                    : k === "rejected"
                      ? "var(--danger)"
                      : "var(--muted)"
              }
            />
          ))}
        </div>
        <div className="card">
          <h3 className="card-title">开门决策</h3>
          <p className="note" style={{ marginBottom: 10 }}>近 24 小时</p>
          <Bar label="grant" value={h24.grant} max={accessMax} color="var(--ok)" />
          <Bar label="deny" value={h24.deny} max={accessMax} color="var(--danger)" />
          <Bar label="skip" value={h24.skip} max={accessMax} color="var(--warn)" />
          <p className="note" style={{ margin: "14px 0 8px" }}>近 7 日 · grant {d7.grant} / deny {d7.deny}</p>
          {(d?.access.top_grant_7d || []).length ? (
            <ul className="mini-list">
              {d!.access.top_grant_7d.map((r) => (
                <li key={r.user_id}>
                  <button type="button" className="linkish" onClick={() => navigate("/gallery")}>
                    {r.user_id}
                  </button>
                  <span>{r.n} 次</span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="note">暂无开门记录</p>
          )}
        </div>
      </div>

      <div className="card" style={{ marginTop: 14 }}>
        <div className="card-head">
          <h3 className="card-title" style={{ margin: 0 }}>
            待重采队列
          </h3>
          <button type="button" className="btn ghost" onClick={() => navigate("/gallery")}>
            打开人脸库
          </button>
        </div>
        {pending.length === 0 ? (
          <p className="note">没有待补采人员</p>
        ) : (
          <div className="list" style={{ marginTop: 10 }}>
            {pending.map((p) => (
              <div className="row compact" key={p.user_id}>
                <div>
                  <h3>{p.display_name || "未命名"}</h3>
                  <div className="sub">{p.user_id}</div>
                </div>
                <button
                  type="button"
                  className="btn primary"
                  onClick={() =>
                    navigate("/capture", {
                      state: {
                        user_id: p.user_id,
                        display_name: p.display_name,
                        face_status: p.face_status,
                      },
                    })
                  }
                >
                  去采集
                </button>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
