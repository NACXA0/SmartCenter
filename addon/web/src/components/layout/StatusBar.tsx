import { useEffect, useState } from "react";
import { api, type Health } from "@/api/client";

export function StatusBar() {
  const [h, setH] = useState<Health | null>(null);

  useEffect(() => {
    let alive = true;
    const load = async () => {
      try {
        const data = await api.health();
        if (alive) setH(data);
      } catch {
        if (alive) setH(null);
      }
    };
    load();
    const t = window.setInterval(load, 15000);
    return () => {
      alive = false;
      window.clearInterval(t);
    };
  }, []);

  const ok = !!h?.ok;
  const mqtt = h?.mqtt_enabled ? h.mqtt_host || "on" : "off";
  return (
    <footer className="statusbar">
      <span className="pill">
        <span className={`dot ${ok ? "ok" : "bad"}`} />
        {h ? (ok ? "ready" : "degraded") : "offline"}
      </span>
      <span className="pill">mqtt {mqtt}</span>
      <span className="pill">model {h?.model_version || "—"}</span>
      {h?.disk_full ? <span className="pill"><span className="dot warn" />disk full</span> : null}
      {typeof h?.store?.match_audit === "number" ? (
        <span className="pill">audit {h.store.match_audit}</span>
      ) : null}
    </footer>
  );
}
