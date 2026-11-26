import { useCallback, useState } from "react";
import { HashRouter, Navigate, Route, Routes, useNavigate } from "react-router-dom";
import { AppShell } from "@/components/layout/AppShell";
import { ToastProvider } from "@/components/ui/Toast";
import { OverviewPage } from "@/pages/OverviewPage";
import { CapturePage } from "@/pages/CapturePage";
import { GalleryPage } from "@/pages/GalleryPage";
import { AuditPage } from "@/pages/AuditPage";
import type { Person } from "@/api/client";

function Workbench() {
  const navigate = useNavigate();
  const [preselect, setPreselect] = useState<Person | null>(null);

  const onRecapture = useCallback(
    (p: Person) => {
      setPreselect(p);
      navigate("/capture");
    },
    [navigate],
  );

  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route path="/" element={<Navigate to="/overview" replace />} />
        <Route path="/overview" element={<OverviewPage />} />
        <Route
          path="/capture"
          element={
            <CapturePage
              preselect={preselect}
              onPreselectConsumed={() => setPreselect(null)}
            />
          }
        />
        <Route path="/gallery" element={<GalleryPage onRecapture={onRecapture} />} />
        <Route path="/audit" element={<AuditPage />} />
        <Route path="*" element={<Navigate to="/overview" replace />} />
      </Route>
    </Routes>
  );
}

export default function App() {
  return (
    <ToastProvider>
      <HashRouter>
        <Workbench />
      </HashRouter>
    </ToastProvider>
  );
}
