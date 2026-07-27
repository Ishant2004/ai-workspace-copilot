import { useState } from "react";
import Chat from "./components/Chat";
import TokenInspector from "./components/TokenInspector";

type Tab = "chat" | "tokens";

// App shell: a header with tabs that switch between the Phase 0 chat and the
// Phase 1 token inspector. Each tab is self-contained.
export default function App() {
  const [tab, setTab] = useState<Tab>("chat");

  return (
    <div className="flex h-screen flex-col bg-neutral-50 text-neutral-900">
      <header className="border-b border-neutral-200 bg-white px-4 py-3">
        <div className="mx-auto flex w-full max-w-2xl items-center justify-between">
          <div>
            <h1 className="text-lg font-semibold">AI Workspace Copilot</h1>
            <p className="text-xs text-neutral-500">Phases 0–1</p>
          </div>
          <nav className="flex gap-1 rounded-lg bg-neutral-100 p-1 text-sm">
            <TabButton active={tab === "chat"} onClick={() => setTab("chat")}>
              Chat
            </TabButton>
            <TabButton
              active={tab === "tokens"}
              onClick={() => setTab("tokens")}
            >
              Token Inspector
            </TabButton>
          </nav>
        </div>
      </header>

      <div className="flex-1 overflow-y-auto">
        {tab === "chat" ? <Chat /> : <TokenInspector />}
      </div>
    </div>
  );
}

function TabButton({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      className={
        "rounded-md px-3 py-1 font-medium transition " +
        (active
          ? "bg-white text-neutral-900 shadow-sm"
          : "text-neutral-500 hover:text-neutral-800")
      }
    >
      {children}
    </button>
  );
}
