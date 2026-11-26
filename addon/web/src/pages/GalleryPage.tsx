import { useCallback, useEffect, useState } from "react";
import * as Select from "@radix-ui/react-select";
import * as Switch from "@radix-ui/react-switch";
import * as Dialog from "@radix-ui/react-dialog";
import { ChevronDown, RefreshCw, UserRound, X } from "lucide-react";
import { api, type Person, type PersonDetail } from "@/api/client";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { useToast } from "@/components/ui/Toast";

type Props = {
  onRecapture: (p: Person) => void;
};

export function GalleryPage({ onRecapture }: Props) {
  const toast = useToast();
  const [q, setQ] = useState("");
  const [filter, setFilter] = useState("");
  const [items, setItems] = useState<Person[]>([]);
  const [pendingDelete, setPendingDelete] = useState<Person | null>(null);
  const [detail, setDetail] = useState<PersonDetail | null>(null);
  const [nameDraft, setNameDraft] = useState("");

  const load = useCallback(async () => {
    try {
      const r = await api.listPersons(q.trim());
      let list = r.items || [];
      if (filter) list = list.filter((p) => p.face_status === filter);
      list.sort((a, b) => (a.face_status === "pending" ? 0 : 1) - (b.face_status === "pending" ? 0 : 1));
      setItems(list);
    } catch (e) {
      toast.push(String(e instanceof Error ? e.message : e));
    }
  }, [q, filter, toast]);

  useEffect(() => {
    const t = window.setTimeout(load, 180);
    return () => window.clearTimeout(t);
  }, [load]);

  const openDetail = async (p: Person) => {
    try {
      const d = await api.personDetail(p.user_id);
      setDetail(d);
      setNameDraft(d.display_name || "");
    } catch (e) {
      toast.push(String(e instanceof Error ? e.message : e));
    }
  };

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1>人脸库</h1>
          <p>本地底库管理 · 启停 / 补采 / 详情帧 · 向量不出店</p>
        </div>
        <button type="button" className="btn ghost" onClick={load}>
          <RefreshCw size={16} /> 刷新
        </button>
      </div>

      <div className="toolbar">
        <input
          className="input"
          type="search"
          placeholder="筛选姓名 / user_id"
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
        <Select.Root value={filter || "all"} onValueChange={(v) => setFilter(v === "all" ? "" : v)}>
          <Select.Trigger className="select-trigger btn" aria-label="状态筛选">
            <Select.Value placeholder="全部状态" />
            <Select.Icon>
              <ChevronDown size={16} />
            </Select.Icon>
          </Select.Trigger>
          <Select.Portal>
            <Select.Content className="rdx-content" position="popper" sideOffset={6}>
              <Select.Viewport>
                {[
                  ["all", "全部状态"],
                  ["pending", "待重采"],
                  ["accepted", "可开门"],
                  ["verified", "已验证"],
                  ["rejected", "已停用"],
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
          <p className="note">人脸库为空或无匹配 — 请到「采集」录入</p>
        ) : (
          items.map((p) => (
            <div className="row" key={p.user_id}>
              <button type="button" className="avatar as-btn" onClick={() => openDetail(p)} title="详情">
                {p.has_thumb ? <img src={api.thumbUrl(p.user_id)} alt="" /> : <UserRound size={18} />}
              </button>
              <button type="button" className="row-main as-btn" onClick={() => openDetail(p)}>
                <h3>{p.display_name || "未命名"}</h3>
                <div className="sub">{p.user_id}</div>
                <div style={{ marginTop: 6 }}>
                  <StatusBadge status={p.face_status} />
                  {typeof p.verify_ok_count === "number" ? (
                    <span className="note" style={{ marginLeft: 8 }}>
                      验证 {p.verify_ok_count}/3
                    </span>
                  ) : null}
                </div>
              </button>
              <div className="row-actions">
                <button type="button" className="btn ghost" onClick={() => onRecapture(p)}>
                  补采
                </button>
                <Switch.Root
                  className="switch"
                  checked={!!p.enabled && p.face_status !== "rejected"}
                  onCheckedChange={async (on) => {
                    try {
                      if (on) await api.enablePerson(p.user_id);
                      else await api.disablePerson(p.user_id);
                      toast.push(on ? "已启用" : "已停用");
                      load();
                    } catch {
                      toast.push("操作失败");
                    }
                  }}
                  aria-label="启用"
                >
                  <Switch.Thumb className="switch-thumb" />
                </Switch.Root>
                <button type="button" className="btn danger" onClick={() => setPendingDelete(p)}>
                  删除
                </button>
              </div>
            </div>
          ))
        )}
      </div>

      <Dialog.Root open={!!detail} onOpenChange={(o) => !o && setDetail(null)}>
        <Dialog.Portal>
          <Dialog.Overlay className="dialog-overlay" />
          <Dialog.Content className="drawer-content" aria-describedby={undefined}>
            <div className="drawer-head">
              <Dialog.Title asChild>
                <h2>人员详情</h2>
              </Dialog.Title>
              <Dialog.Close asChild>
                <button type="button" className="btn icon ghost" aria-label="关闭">
                  <X size={18} />
                </button>
              </Dialog.Close>
            </div>
            {detail ? (
              <>
                <div className="drawer-meta">
                  <StatusBadge status={detail.face_status} />
                  <span className="sub">user_id {detail.user_id}</span>
                </div>
                <label className="field" htmlFor="rename">
                  显示名
                </label>
                <div className="actions" style={{ marginBottom: 14 }}>
                  <input
                    id="rename"
                    className="input"
                    value={nameDraft}
                    onChange={(e) => setNameDraft(e.target.value)}
                  />
                  <button
                    type="button"
                    className="btn"
                    onClick={async () => {
                      try {
                        await api.renamePerson(detail.user_id, nameDraft);
                        toast.push("已更新姓名");
                        load();
                        openDetail(detail);
                      } catch {
                        toast.push("保存失败");
                      }
                    }}
                  >
                    保存
                  </button>
                </div>
                <p className="note">
                  验证成功 {detail.verify_ok_count ?? 0} · 连续失败 {detail.verify_fail_streak ?? 0} · 合格帧{" "}
                  {detail.frame_count}
                </p>
                <div className="field" style={{ marginTop: 12 }}>
                  合格帧
                </div>
                <div className="thumbs">
                  {(detail.frames || []).map((f) => (
                    <div className="slot filled" key={f.index}>
                      <img src={api.frameUrl(detail.user_id, f.index)} alt="" />
                    </div>
                  ))}
                  {!detail.frames?.length ? <p className="note">无本地帧（可能仅有向量）</p> : null}
                </div>
                <div className="actions" style={{ marginTop: 18 }}>
                  <button
                    type="button"
                    className="btn primary"
                    onClick={() => {
                      onRecapture(detail);
                      setDetail(null);
                    }}
                  >
                    补采
                  </button>
                  <button
                    type="button"
                    className="btn danger"
                    onClick={() => {
                      setPendingDelete(detail);
                      setDetail(null);
                    }}
                  >
                    删除
                  </button>
                </div>
              </>
            ) : null}
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>

      <ConfirmDialog
        open={!!pendingDelete}
        title="删除人脸库记录？"
        description={`将删除 ${pendingDelete?.display_name || pendingDelete?.user_id || ""} 的本地向量与合格帧，不可恢复。`}
        confirmLabel="删除"
        onOpenChange={(o) => !o && setPendingDelete(null)}
        onConfirm={async () => {
          if (!pendingDelete) return;
          try {
            await api.deletePerson(pendingDelete.user_id);
            toast.push("已删除");
            load();
          } catch {
            toast.push("删除失败");
          }
        }}
      />
    </div>
  );
}
