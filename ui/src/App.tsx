import { useEffect, useState } from "react";
import { Link, Route, Routes, useLocation } from "react-router-dom";
import { IndexTabs, Sheet, Spine, FolioHead, type TabDef } from "./components/Book";
import { SlipProvider } from "./components/Toast";
import { api } from "./lib/api";
import { AskPage } from "./pages/Ask";
import { FolioPage } from "./pages/Folio";
import { LedgerPage } from "./pages/LedgerPage";
import { PostStatementPage } from "./pages/PostStatement";
import { ReportsPage } from "./pages/Reports";
import { ReviewPage } from "./pages/Review";
import { SettingsPage } from "./pages/Settings";
import { StandingChargesPage } from "./pages/StandingCharges";

function useBacklog(): number {
  const { pathname } = useLocation();
  const [backlog, setBacklog] = useState(0);
  useEffect(() => {
    let live = true;
    api.stats().then((s) => { if (live) setBacklog(s.review_backlog); }, () => {});
    return () => { live = false; };
  }, [pathname]);
  return backlog;
}

function NotFound() {
  return (
    <Sheet>
      <FolioHead kicker="Page not found" title="This page was torn out">
        There is no such page in this ledger. <Link to="/">Back to this month's folio</Link>.
      </FolioHead>
    </Sheet>
  );
}

export function App() {
  const backlog = useBacklog();
  const tabs: TabDef[] = [
    { to: "/", label: "Overview" },
    { to: "/import", label: "Import" },
    { to: "/review", label: "Review", count: backlog },
    { to: "/audit", label: "Audit" },
    { to: "/ledger", label: "Ledger" },
    { to: "/ask", label: "Ask" },
    { to: "/reports", label: "Reports" },
    { to: "/recurring", label: "Recurring" },
    { to: "/settings", label: "Settings" },
  ];
  return (
    <SlipProvider>
      <a href="#main" className="skip-link">Skip to the page</a>
      <div className="book">
        <Spine />
        <IndexTabs tabs={tabs} />
        <Routes>
          <Route path="/" element={<FolioPage />} />
          <Route path="/import" element={<PostStatementPage />} />
          <Route path="/review" element={<ReviewPage mode="review" />} />
          <Route path="/audit" element={<ReviewPage mode="audit" />} />
          <Route path="/ledger" element={<LedgerPage />} />
          <Route path="/ask" element={<AskPage />} />
          <Route path="/reports" element={<ReportsPage />} />
          <Route path="/recurring" element={<StandingChargesPage />} />
          <Route path="/settings" element={<SettingsPage />} />
          <Route path="*" element={<NotFound />} />
        </Routes>
      </div>
    </SlipProvider>
  );
}
