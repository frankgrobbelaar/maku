import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { HashRouter, Route, Routes } from "react-router";
import { ScreenError } from "@/components/screen-error";
import { AppShell } from "@/components/shell/app-shell";
import { UpdateCard } from "@/components/shell/update-card";
import { ConvertPage } from "@/features/convert/convert-page";
import { QueuePage } from "@/features/convert/queue-page";
import { FranchisePage } from "@/features/franchise/franchise-page";
import { HistoryPage } from "@/features/history/history-page";
import { HomePage } from "@/features/home/home-page";
import { MatchPage } from "@/features/match/match-page";
import { ScanPage } from "@/features/scan/scan-page";
import { SettingsPage } from "@/features/settings/settings-page";
import { SetupPage } from "@/features/setup/setup-page";
import { MakeSubtitlesPage } from "@/features/subtitles/make-page";
import { TidyPage } from "@/features/tidy/tidy-page";
import { TitlePage } from "@/features/title/title-page";
import { EngineProvider } from "@/lib/engine";

const queryClient = new QueryClient();

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <EngineProvider>
        <HashRouter>
          <Routes>
            <Route
              path="/setup"
              element={
                <ScreenError>
                  <SetupPage />
                </ScreenError>
              }
            />
            <Route element={<AppShell />}>
              <Route index element={<HomePage />} />
              <Route path="/scan" element={<ScanPage />} />
              <Route path="/match" element={<MatchPage />} />
              <Route path="/titles/:id" element={<TitlePage />} />
              <Route path="/franchises/:id" element={<FranchisePage />} />
              <Route path="/tidy" element={<TidyPage />} />
              <Route path="/convert" element={<ConvertPage />} />
              <Route path="/convert/queue" element={<QueuePage />} />
              <Route path="/subtitles" element={<MakeSubtitlesPage />} />
              <Route path="/history" element={<HistoryPage />} />
              <Route path="/settings" element={<SettingsPage />} />
              <Route path="/settings/:section" element={<SettingsPage />} />
            </Route>
          </Routes>
          <SetupUpdates />
        </HashRouter>
      </EngineProvider>
    </QueryClientProvider>
  );
}

/** The update card lives in the shell; setup has its own frame, so it shows the card itself. */
function SetupUpdates() {
  return (
    <Routes>
      <Route path="/setup" element={<UpdateCard />} />
      <Route path="*" element={null} />
    </Routes>
  );
}
