import { useCallback, useEffect, useRef, useState } from "react";
import { useLocation } from "react-router-dom";
import { Play, Square } from "lucide-react";
import { api, type Person } from "@/api/client";
import { PersonPicker } from "@/components/PersonPicker";
import { useToast } from "@/components/ui/Toast";

type Props = {
  preselect?: Person | null;
  onPreselectConsumed?: () => void;
};

export function CapturePage({ preselect, onPreselectConsumed }: Props) {
  const toast = useToast();
  const location = useLocation();
  const videoRef = useRef<HTMLVideoElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const loopRef = useRef<number | null>(null);
  const sessionRef = useRef<string | null>(null);

  const [selected, setSelected] = useState<Person | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [needed, setNeeded] = useState(5);
  const [progress, setProgress] = useState(0);
  const [thumbs, setThumbs] = useState<(string | null)[]>([]);
  const [hint, setHint] = useState("请先搜索并选中学员，再开始会话");
  const [hintOk, setHintOk] = useState<boolean | null>(null);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (preselect) {
      setSelected(preselect);
      onPreselectConsumed?.();
      return;
    }
    const st = location.state as Person | null;
    if (st?.user_id) setSelected(st);
  }, [preselect, onPreselectConsumed, location.state]);

  const ensureCamera = useCallback(async () => {
    if (streamRef.current) return;
    const stream = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: "user", width: { ideal: 1280 }, height: { ideal: 720 } },
      audio: false,
    });
    streamRef.current = stream;
    if (videoRef.current) videoRef.current.srcObject = stream;
  }, []);

  useEffect(() => {
    if (selected) {
      ensureCamera().catch((e) => toast.push(String(e.message || e)));
    }
  }, [selected, ensureCamera, toast]);

  useEffect(() => {
    return () => {
      if (loopRef.current) window.clearInterval(loopRef.current);
      streamRef.current?.getTracks().forEach((t) => t.stop());
    };
  }, []);

  const stopLoop = useCallback(
    (cancelServer: boolean) => {
      if (loopRef.current) {
        window.clearInterval(loopRef.current);
        loopRef.current = null;
      }
      if (cancelServer && sessionRef.current) {
        api.enrollCancel(sessionRef.current).catch(() => undefined);
        sessionRef.current = null;
        setSessionId(null);
      }
    },
    [],
  );

  const pushFrame = useCallback(async () => {
    const sid = sessionRef.current;
    const video = videoRef.current;
    const canvas = canvasRef.current;
    if (!sid || !video || !canvas) return;
    const w = video.videoWidth;
    const h = video.videoHeight;
    if (!w || !h) return;
    canvas.width = w;
    canvas.height = h;
    canvas.getContext("2d")?.drawImage(video, 0, 0, w, h);
    const blob = await new Promise<Blob | null>((res) => canvas.toBlob(res, "image/jpeg", 0.88));
    if (!blob) return;
    const j = await api.enrollFrame(sid, blob);
    if (typeof j.needed === "number") setNeeded(j.needed);
    if (typeof j.progress === "number") setProgress(j.progress);
    if (j.ok) {
      setHint(j.hint || "合格");
      setHintOk(true);
      const url = URL.createObjectURL(blob);
      setThumbs((prev) => {
        const next = [...prev];
        next[Math.max(0, (j.progress || 1) - 1)] = url;
        return next;
      });
    } else {
      setHint(j.hint || j.reason || "请调整");
      setHintOk(false);
    }
    setReason(j.reason || "");
    if (j.done) {
      stopLoop(false);
      sessionRef.current = null;
      setSessionId(null);
      setHint(`采集完成：${j.face_status || "accepted"} · 可让学生去门口试刷`);
      setHintOk(true);
      toast.push("✓ 已录入底库");
      setSelected((s) => (s ? { ...s, face_status: j.face_status || "accepted" } : s));
    }
  }, [stopLoop, toast]);

  const onStart = async () => {
    if (!selected || busy) return;
    setBusy(true);
    try {
      await ensureCamera();
      stopLoop(true);
      setProgress(0);
      setThumbs([]);
      setNeeded(5);
      const j = await api.enrollStart(selected.user_id, selected.display_name || "");
      sessionRef.current = j.session_id;
      setSessionId(j.session_id);
      setNeeded(j.needed || 5);
      setHint("会话进行中 · 自动质检送帧");
      setHintOk(true);
      loopRef.current = window.setInterval(() => {
        pushFrame().catch((e) => {
          setHint(String(e));
          setHintOk(false);
        });
      }, 650);
    } catch (e) {
      setHint(String(e instanceof Error ? e.message : e));
      setHintOk(false);
    } finally {
      setBusy(false);
    }
  };

  const onStop = () => {
    stopLoop(true);
    setHint("会话已结束");
    setHintOk(null);
  };

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1>采集</h1>
          <p>仅摄像头实时采集 · 开始后自动质检送帧</p>
        </div>
      </div>

      <PersonPicker selected={selected} onSelect={setSelected} />

      <div className="capture-grid" style={{ marginTop: 14 }}>
        <div className="stage">
          <video ref={videoRef} playsInline autoPlay muted />
          <div className="guide" aria-hidden />
        </div>
        <div className="side-stack">
          <div className="card">
            <div className="progress-row">
              <span>
                进度 <b>{progress} / {needed}</b>
              </span>
              <div className="dots">
                {Array.from({ length: needed }).map((_, i) => (
                  <span key={i} className={i < progress ? "on" : ""} />
                ))}
              </div>
            </div>
            <div style={{ marginTop: 12 }}>
              <div className={`hint${hintOk === true ? " ok" : hintOk === false ? " bad" : ""}`}>
                {hint}
              </div>
              {reason ? (
                <p className="note" style={{ marginTop: 8 }}>
                  原因码 <code style={{ fontFamily: "var(--mono)" }}>{reason}</code>
                </p>
              ) : null}
            </div>
            <div className="actions" style={{ marginTop: 14 }}>
              <button
                type="button"
                className="btn primary"
                disabled={!selected || !!sessionId || busy}
                onClick={onStart}
              >
                <Play size={16} /> 开始会话
              </button>
              <button type="button" className="btn danger" disabled={!sessionId} onClick={onStop}>
                <Square size={16} /> 结束
              </button>
            </div>
            <p className="note" style={{ marginTop: 12 }}>
              不提供相册上传。管理员只需选人、开始，让学生站好即可。
            </p>
          </div>
          <div className="card">
            <div className="field">合格帧</div>
            <div className="thumbs">
              {Array.from({ length: needed }).map((_, i) => (
                <div key={i} className={`slot${thumbs[i] ? " filled" : ""}`}>
                  {thumbs[i] ? <img src={thumbs[i]!} alt="" /> : null}
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
      <canvas ref={canvasRef} style={{ display: "none" }} />
    </div>
  );
}
