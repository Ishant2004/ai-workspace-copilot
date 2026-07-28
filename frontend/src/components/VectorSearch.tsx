import { useCallback, useEffect, useRef, useState } from "react";
import {
  addDocument,
  updateDocument,
  deleteDocument,
  listDocuments,
  searchDocuments,
  uploadPdf,
  type DocMetadata,
  type DocumentItem,
  type SearchHit,
} from "../services/api";

// Phase 3: Vector database demo (with full CRUD).
// Phase 5: also ingest PDFs (extract -> chunk -> embed -> store).
//
// The loop:
//   1. Add / edit documents -> backend embeds them and stores them in pgvector.
//   2. Upload a PDF          -> backend chunks + embeds it into many documents.
//   3. Manage documents      -> list, edit (re-embeds), delete.
//   4. Search                -> backend embeds the query and returns the nearest
//                               documents by cosine similarity.
// The similarity score (0..1) shows this is *meaning-based* matching, not
// keyword matching — a query can rank a document highly with no shared words.

export default function VectorSearch() {
  const [docs, setDocs] = useState<DocumentItem[]>([]);
  const [dbError, setDbError] = useState<string | null>(null);

  // PDF upload state.
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadMsg, setUploadMsg] = useState<string | null>(null);

  // Form state — shared by "add" and "edit". editingId === null means adding.
  const [editingId, setEditingId] = useState<number | null>(null);
  const [docTitle, setDocTitle] = useState("");
  const [docText, setDocText] = useState("");
  const [saving, setSaving] = useState(false);
  const [addMsg, setAddMsg] = useState<string | null>(null);

  // Search state.
  const [query, setQuery] = useState("");
  const [searching, setSearching] = useState(false);
  const [hits, setHits] = useState<SearchHit[] | null>(null);
  const [searchError, setSearchError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      setDocs(await listDocuments());
      setDbError(null);
    } catch (e) {
      setDbError(e instanceof Error ? e.message : "Failed to reach the DB");
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  function resetForm() {
    setEditingId(null);
    setDocTitle("");
    setDocText("");
  }

  async function onSave() {
    if (!docText.trim() || saving) return;
    setSaving(true);
    setAddMsg(null);
    try {
      if (editingId === null) {
        const res = await addDocument(docText.trim(), docTitle.trim());
        setAddMsg(`Stored document #${res.id}.`);
      } else {
        await updateDocument(editingId, docText.trim(), docTitle.trim());
        setAddMsg(`Updated document #${editingId}.`);
      }
      resetForm();
      await refresh();
    } catch (e) {
      setAddMsg(e instanceof Error ? e.message : "Failed to save document");
    } finally {
      setSaving(false);
    }
  }

  async function onUpload(file: File) {
    setUploading(true);
    setUploadMsg(null);
    try {
      const res = await uploadPdf(file);
      setUploadMsg(
        `Ingested "${res.filename}" (${res.pages} page(s)) → ${res.chunks_stored} chunks stored.`
      );
      await refresh();
    } catch (e) {
      setUploadMsg(e instanceof Error ? e.message : "Upload failed");
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = ""; // allow re-upload
    }
  }

  function onEdit(doc: DocumentItem) {
    setEditingId(doc.id);
    setDocTitle(doc.title);
    setDocText(doc.text);
    setAddMsg(null);
  }

  async function onDelete(id: number) {
    try {
      await deleteDocument(id);
      if (editingId === id) resetForm();
      await refresh();
    } catch (e) {
      setAddMsg(e instanceof Error ? e.message : "Failed to delete document");
    }
  }

  async function onSearch() {
    if (!query.trim() || searching) return;
    setSearching(true);
    setSearchError(null);
    try {
      setHits(await searchDocuments(query.trim(), 5));
    } catch (e) {
      setSearchError(e instanceof Error ? e.message : "Search failed");
      setHits(null);
    } finally {
      setSearching(false);
    }
  }

  const editing = editingId !== null;

  return (
    <div className="mx-auto w-full max-w-2xl space-y-6 p-4">
      <div className="flex items-center justify-between">
        <p className="text-sm text-neutral-500">
          Store documents, then search them by meaning (cosine similarity over
          pgvector).
        </p>
        <span className="shrink-0 rounded-full bg-neutral-100 px-3 py-1 text-xs font-medium text-neutral-600">
          {dbError ? "—" : `${docs.length} docs`}
        </span>
      </div>

      {dbError && (
        <p className="rounded-lg bg-amber-50 p-3 text-sm text-amber-700">
          {dbError} — is <code>DATABASE_URL</code> set and the backend running?
        </p>
      )}

      {/* Add / edit document */}
      <section className="space-y-2 rounded-lg border border-neutral-200 bg-white p-4">
        <h2 className="text-sm font-semibold">
          {editing ? `Edit document #${editingId}` : "Add a document"}
        </h2>
        <input
          className="w-full rounded-lg border border-neutral-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
          placeholder="Title (optional)"
          value={docTitle}
          onChange={(e) => setDocTitle(e.target.value)}
        />
        <textarea
          className="h-24 w-full resize-none rounded-lg border border-neutral-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
          placeholder="Document text to store…"
          value={docText}
          onChange={(e) => setDocText(e.target.value)}
        />
        <div className="flex items-center gap-3">
          <button
            className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white disabled:opacity-40"
            onClick={onSave}
            disabled={saving || !docText.trim()}
          >
            {saving
              ? editing
                ? "Saving…"
                : "Embedding & storing…"
              : editing
                ? "Save changes"
                : "Add document"}
          </button>
          {editing && (
            <button
              className="rounded-lg px-3 py-2 text-sm font-medium text-neutral-500 hover:text-neutral-800"
              onClick={resetForm}
            >
              Cancel
            </button>
          )}
          {addMsg && <span className="text-sm text-neutral-500">{addMsg}</span>}
        </div>
      </section>

      {/* Upload a PDF (Phase 5) */}
      <section className="space-y-2 rounded-lg border border-neutral-200 bg-white p-4">
        <h2 className="text-sm font-semibold">Upload a PDF</h2>
        <p className="text-xs text-neutral-500">
          The PDF is split into overlapping chunks, each embedded and stored as
          a document — so its content becomes searchable and usable for RAG.
        </p>
        <div className="flex items-center gap-3">
          <input
            ref={fileInputRef}
            type="file"
            accept="application/pdf"
            disabled={uploading}
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) onUpload(f);
            }}
            className="text-sm file:mr-3 file:rounded-lg file:border-0 file:bg-blue-600 file:px-4 file:py-2 file:text-sm file:font-medium file:text-white hover:file:bg-blue-700 disabled:opacity-40"
          />
          {uploading && (
            <span className="text-sm text-neutral-500">Ingesting…</span>
          )}
        </div>
        {uploadMsg && <p className="text-sm text-neutral-600">{uploadMsg}</p>}
      </section>

      {/* Stored documents (manage) */}
      {docs.length > 0 && (
        <section className="space-y-2 rounded-lg border border-neutral-200 bg-white p-4">
          <h2 className="text-sm font-semibold">Stored documents</h2>
          <div className="space-y-2">
            {docs.map((d) => (
              <div
                key={d.id}
                className="flex items-start justify-between gap-3 rounded-lg border border-neutral-200 p-3"
              >
                <div className="min-w-0">
                  <div className="text-sm font-medium">
                    {d.title || `Document #${d.id}`}
                    <span className="ml-2 font-mono text-xs text-neutral-400">
                      #{d.id}
                    </span>
                  </div>
                  <p className="line-clamp-2 text-sm text-neutral-600">
                    {d.text}
                  </p>
                  <MetaLine meta={d.metadata} />
                </div>
                <div className="flex shrink-0 gap-1">
                  <button
                    className="rounded-md px-2 py-1 text-xs font-medium text-blue-600 hover:bg-blue-50"
                    onClick={() => onEdit(d)}
                  >
                    Edit
                  </button>
                  <button
                    className="rounded-md px-2 py-1 text-xs font-medium text-red-600 hover:bg-red-50"
                    onClick={() => onDelete(d.id)}
                  >
                    Delete
                  </button>
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      {/* Search */}
      <section className="space-y-2 rounded-lg border border-neutral-200 bg-white p-4">
        <h2 className="text-sm font-semibold">Search</h2>
        <div className="flex gap-2">
          <input
            className="flex-1 rounded-lg border border-neutral-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
            placeholder="Ask something…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && onSearch()}
          />
          <button
            className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white disabled:opacity-40"
            onClick={onSearch}
            disabled={searching || !query.trim()}
          >
            {searching ? "Searching…" : "Search"}
          </button>
        </div>

        {searchError && (
          <p className="text-sm text-red-600">[error] {searchError}</p>
        )}

        {hits && hits.length === 0 && (
          <p className="text-sm text-neutral-400">
            No documents yet — add some above.
          </p>
        )}

        <div className="space-y-2">
          {hits?.map((h) => (
            <div
              key={h.id}
              className="rounded-lg border border-neutral-200 p-3"
            >
              <div className="mb-1 flex items-center justify-between gap-2">
                <span className="text-sm font-medium">
                  {h.title || `Document #${h.id}`}
                </span>
                <SimilarityBadge score={h.similarity} />
              </div>
              <p className="line-clamp-3 text-sm text-neutral-600">{h.text}</p>
              <MetaLine meta={h.metadata} />
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}

// Shows a document's provenance (Phase 6 metadata): source, filename, page.
// Renders nothing when there's no useful metadata (e.g. older rows).
function MetaLine({ meta }: { meta?: DocMetadata }) {
  if (!meta) return null;
  const bits: string[] = [];
  if (meta.source === "pdf" && meta.filename) bits.push(meta.filename);
  else if (meta.source) bits.push(meta.source);
  if (meta.page != null) bits.push(`p.${meta.page}`);
  if (bits.length === 0) return null;
  return (
    <div className="mt-1 flex flex-wrap gap-1">
      {bits.map((b, i) => (
        <span
          key={i}
          className="rounded bg-neutral-100 px-1.5 py-0.5 text-[11px] text-neutral-500"
        >
          {b}
        </span>
      ))}
    </div>
  );
}

function SimilarityBadge({ score }: { score: number }) {
  // Green when clearly relevant, amber for so-so, grey for weak matches.
  const pct = (score * 100).toFixed(1);
  const color =
    score >= 0.7
      ? "bg-green-100 text-green-700"
      : score >= 0.5
        ? "bg-amber-100 text-amber-700"
        : "bg-neutral-100 text-neutral-500";
  return (
    <span
      className={`shrink-0 rounded-full px-2 py-0.5 text-xs font-medium ${color}`}
    >
      {pct}% match
    </span>
  );
}
