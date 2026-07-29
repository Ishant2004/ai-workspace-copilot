import { useState } from "react";
import Chat from "./components/Chat";
import TokenInspector from "./components/TokenInspector";
import EmbedInspector from "./components/EmbedInspector";
import VectorSearch from "./components/VectorSearch";

type Tab = "chat" | "tokens" | "embed" | "search";

// App shell: a header with tabs.
//
// Every tab component stays MOUNTED for the whole session; we only hide the
// inactive ones with `hidden` (display:none). Mounting/unmounting on each
// switch would reset each component's internal state — you'd lose your chat,
// your typed text, your search results — so we keep them alive instead.
export default function App() {
  const [tab, setTab] = useState<Tab>("chat");

  return (
    <div className="flex h-screen flex-col bg-neutral-50 text-neutral-900">
      <header className="border-b border-neutral-200 bg-white px-4 py-3">
        <div className="mx-auto flex w-full max-w-2xl items-center justify-between">
          <div>
            <h1 className="text-lg font-semibold">AI Workspace Copilot</h1>
            <p className="text-xs text-neutral-500">Phases 0–11</p>
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
            <TabButton
              active={tab === "embed"}
              onClick={() => setTab("embed")}
            >
              Embeddings
            </TabButton>
            <TabButton
              active={tab === "search"}
              onClick={() => setTab("search")}
            >
              Vector Search
            </TabButton>
          </nav>
        </div>
      </header>

      <div className="flex-1 overflow-y-auto">
        {/* All tabs stay mounted; only the active one is visible. */}
        <TabPanel active={tab === "chat"}>
          <Chat />
        </TabPanel>
        <TabPanel active={tab === "tokens"}>
          <TokenInspector />
        </TabPanel>
        <TabPanel active={tab === "embed"}>
          <EmbedInspector />
        </TabPanel>
        <TabPanel active={tab === "search"}>
          <VectorSearch />
        </TabPanel>
      </div>
    </div>
  );
}

// Keeps its children mounted but hides them (display:none) when inactive, so
// component state survives tab switches. The active panel gets full height so
// the chat's sticky footer still lays out correctly.
function TabPanel({
  active,
  children,
}: {
  active: boolean;
  children: React.ReactNode;
}) {
  return <div className={active ? "h-full" : "hidden"}>{children}</div>;
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
