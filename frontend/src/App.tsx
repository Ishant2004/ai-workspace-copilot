import { useEffect, useState } from "react";
import Chat from "./components/Chat";
import TokenInspector from "./components/TokenInspector";
import EmbedInspector from "./components/EmbedInspector";
import VectorSearch from "./components/VectorSearch";
import Auth from "./components/Auth";
import {
  authToken,
  logout,
  refreshSession,
  setAuthErrorHandler,
} from "./services/api";

type Tab = "chat" | "tokens" | "embed" | "search";

// App shell: a header with tabs.
//
// Every tab component stays MOUNTED for the whole session; we only hide the
// inactive ones with `hidden` (display:none). Mounting/unmounting on each
// switch would reset each component's internal state — you'd lose your chat,
// your typed text, your search results — so we keep them alive instead.
export default function App() {
  const [tab, setTab] = useState<Tab>("chat");
  const [authed, setAuthed] = useState<boolean>(() => !!authToken.get());

  // A 401 anywhere (expired/invalid token) drops back to the login screen.
  useEffect(() => {
    setAuthErrorHandler(() => setAuthed(false));
  }, []);

  // Phase 29: slide the session on load so an active user gets a fresh token
  // instead of being logged out when the old one eventually expires.
  useEffect(() => {
    if (authToken.get()) refreshSession();
  }, []);

  function signOut() {
    logout();
    setAuthed(false);
  }

  // Not signed in → show the auth screen. When it succeeds the whole app
  // subtree mounts fresh, so each tab loads the new user's own data.
  if (!authed) return <Auth onAuthed={() => setAuthed(true)} />;

  return (
    <div className="flex h-[100dvh] flex-col bg-neutral-50 text-neutral-900">
      <header className="border-b border-neutral-200 bg-white px-4 py-3">
        <div className="mx-auto flex w-full max-w-5xl flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-center justify-between">
            <h1 className="text-lg font-semibold">AI Workspace Copilot</h1>
            {/* On mobile Sign out sits with the title; on desktop it's in the nav. */}
            <button
              onClick={signOut}
              className="text-sm font-medium text-neutral-500 hover:text-red-600 sm:hidden"
            >
              Sign out
            </button>
          </div>
          <nav className="no-scrollbar flex gap-1 overflow-x-auto rounded-lg bg-neutral-100 p-1 text-sm">
            <TabButton active={tab === "chat"} onClick={() => setTab("chat")}>
              Chat
            </TabButton>
            <TabButton
              active={tab === "tokens"}
              onClick={() => setTab("tokens")}
            >
              Tokens
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
              Search
            </TabButton>
            <button
              onClick={signOut}
              className="hidden shrink-0 rounded-md px-3 py-1 font-medium text-neutral-500 hover:text-red-600 sm:block"
              title="Sign out"
            >
              Sign out
            </button>
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
        "shrink-0 whitespace-nowrap rounded-md px-3 py-1 font-medium transition " +
        (active
          ? "bg-white text-neutral-900 shadow-sm"
          : "text-neutral-500 hover:text-neutral-800")
      }
    >
      {children}
    </button>
  );
}
