import React, { useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";

const API = import.meta.env.VITE_API_URL || "http://127.0.0.1:5000";
const TABS = [["ask", "Ask"], ["search", "Search"], ["transcript", "Transcript"], ["outline", "Outline"]];

async function call(path, options) {
  const r = await fetch(`${API}${path}`, options);
  let d = {};
  try { d = await r.json(); } catch { /* non-JSON response */ }
  if (!r.ok || d.success === false) {
    const err = new Error(d.error || "Request failed. Is the backend running?");
    err.code = d.code; err.manualImport = Boolean(d.manual_import_available);
    throw err;
  }
  return d;
}
const post = (path, body) => call(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
const ytUrl = (id, s = 0) => `https://www.youtube.com/watch?v=${encodeURIComponent(id)}&t=${Math.max(0, Math.floor(Number(s) || 0))}s`;
const pad = (n) => String(n).padStart(2, "0");
function time(s) {
  const n = Math.floor(Number(s) || 0), h = Math.floor(n / 3600), m = Math.floor((n % 3600) / 60);
  return h ? `${pad(h)}:${pad(m)}:${pad(n % 60)}` : `${pad(m)}:${pad(n % 60)}`;
}
const pct = (v) => `${Math.round(Math.max(0, Math.min(1, Number(v) || 0)) * 100)}%`;

function Evidence({ sources, videoId, jump }) {
  const [all, setAll] = useState(false);
  const shown = all ? sources : sources.slice(0, 2);
  return <div className="evidence">
    <h4>Evidence from the transcript</h4>
    {shown.map((s) => <blockquote key={s.chunk_index}>
      <div className="ev-meta">
        <button className="ts" onClick={() => jump(s.start_time)} title="Play from here">▶ {time(s.start_time)}–{time(s.end_time)}</button>
        <a href={ytUrl(videoId, s.start_time)} target="_blank" rel="noreferrer">YouTube ↗</a>
      </div>
      <p>{s.text}</p>
    </blockquote>)}
    {sources.length > 2 && <button className="link" onClick={() => setAll(!all)}>{all ? "Show fewer" : `Show ${sources.length - 2} more passage${sources.length - 2 > 1 ? "s" : ""}`}</button>}
  </div>;
}

function Answer({ item, videoId, jump }) {
  const a = item.a;
  const note = !a ? "" : a.supported ? "Grounded in transcript" : a.grounding?.status === "fallback_evidence" ? "AI unavailable — showing transcript evidence" : "Not enough evidence in the transcript";
  return <div className="turn">
    <p className="q">{item.q}</p>
    {item.pending && <p className="muted"><i className="spin" /> Reading the transcript…</p>}
    {item.err && <p className="err" role="alert">{item.err}</p>}
    {a && <div className="a">
      <span className={`note ${a.supported ? "ok" : "warn"}`}>{note}</span>
      <p className="a-text">{a.answer}</p>
      {a.sources?.length > 0 && <Evidence sources={a.sources} videoId={videoId} jump={jump} />}
    </div>}
  </div>;
}

function ImportPanel({ busy, onImport, onClose }) {
  const [text, setText] = useState("");
  const [fileName, setFileName] = useState("");
  async function pick(e) {
    const f = e.target.files?.[0];
    if (!f) return;
    setFileName(f.name); setText(await f.text());
  }
  return <section className="import" aria-label="Import transcript manually">
    <div className="import-head">
      <h3>Import the transcript yourself</h3>
      <button className="link" onClick={onClose}>Close</button>
    </div>
    <p className="muted">On YouTube: open the video → <b>…more</b> → <b>Show transcript</b> → select and copy all, then paste below. You can also upload a <code>.srt</code>, <code>.vtt</code> or <code>.txt</code> file. Timestamps are kept when present; plain text gets estimated timestamps.</p>
    <textarea rows="7" value={text} onChange={(e) => { setText(e.target.value); setFileName(""); }} aria-label="Transcript text" placeholder="Paste the transcript here…" />
    <div className="import-actions">
      <label className="file-btn">Upload file<input type="file" accept=".txt,.srt,.vtt,text/plain" onChange={pick} hidden /></label>
      {fileName && <span className="muted">{fileName}</span>}
      <button className="btn" disabled={busy || !text.trim()} onClick={() => onImport(text)}>{busy ? <><i className="spin" />Importing</> : "Import & analyze"}</button>
    </div>
  </section>;
}

function App() {
  const [url, setUrl] = useState("");
  const [video, setVideo] = useState(null);
  const [transcript, setTranscript] = useState([]);
  const [knowledge, setKnowledge] = useState(null);
  const [mode, setMode] = useState("stored");
  const [tab, setTab] = useState("ask");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [showImport, setShowImport] = useState(false);
  const [index, setIndex] = useState({ indexed: false, loading: false, error: "" });
  const [embed, setEmbed] = useState({ start: 0, auto: false });
  const [thread, setThread] = useState([]);
  const [askText, setAskText] = useState("");
  const [searchText, setSearchText] = useState("");
  const [results, setResults] = useState(null);
  const [searching, setSearching] = useState(false);
  const [filter, setFilter] = useState("");
  const playerRef = useRef(null);
  const endRef = useRef(null);
  const asking = thread.some((t) => t.pending);

  useEffect(() => {
    const scroller = endRef.current?.closest(".scroll");
    if (scroller) scroller.scrollTo({ top: scroller.scrollHeight, behavior: "smooth" });
  }, [thread]);

  async function ensureIndex(id, force = false) {
    setIndex({ indexed: false, loading: true, error: "" });
    try {
      const st = await call(`/api/videos/${id}/index`);
      if (st.index?.indexed && !force) { setIndex({ ...st.index, indexed: true, loading: false, error: "" }); return true; }
      const b = await post(`/api/videos/${id}/index`, {}); // same POST as before, empty body
      setIndex({ ...b.index, indexed: true, loading: false, error: "" });
      return true;
    } catch (e) { setIndex({ indexed: false, loading: false, error: e.message }); return false; }
  }

  const analyze = (e) => { e.preventDefault(); return run(); };

  async function run(transcriptText) {
    if (!url.trim() || loading) return;
    setLoading(true); setError("");
    try {
      const d = await post("/api/videos/process", transcriptText ? { url, transcript_text: transcriptText } : { url });
      const id = d.video.youtube_video_id;
      const x = await call(`/api/videos/${id}/explorer`);
      setVideo(x.video); setTranscript(x.transcript || []); setKnowledge(x.knowledge || null);
      setMode(d.knowledge_mode || "stored"); setEmbed({ start: 0, auto: false });
      setThread([]); setResults(null); setSearchText(""); setFilter(""); setTab("ask");
      setShowImport(false);
      if (d.import_info?.timestamps_estimated) setError("Imported plain text without timestamps, so times are estimated. Use a timestamped transcript for exact jump links.");
      ensureIndex(id);
    } catch (err) {
      setError(err.message);
      if (err.manualImport || err.code === "TRANSCRIPT_BLOCKED") setShowImport(true);
    }
    finally { setLoading(false); }
  }

  async function ask(q) {
    q = (q ?? askText).trim();
    if (!video || !q || asking) return;
    setAskText(""); setTab("ask");
    setThread((t) => [...t, { q, pending: true }]);
    const finish = (patch) => setThread((t) => t.map((x, i) => (i === t.length - 1 ? { q, ...patch } : x)));
    try { finish({ a: await post(`/api/videos/${video.youtube_video_id}/ask`, { question: q, top_k: 6 }) }); }
    catch (err) { finish({ err: err.message }); }
  }

  async function search(e, q) {
    e?.preventDefault();
    q = (q ?? searchText).trim();
    if (!video || !q) return;
    setSearchText(q); setSearching(true); setError("");
    try {
      if (!index.indexed && !(await ensureIndex(video.youtube_video_id))) throw new Error("The search index isn't ready yet. Use “Retry” under the video.");
      const d = await call(`/api/videos/${video.youtube_video_id}/search?q=${encodeURIComponent(q)}&top_k=8`);
      setResults({ q, items: d.results || [] });
    } catch (err) { setError(err.message); }
    finally { setSearching(false); }
  }

  function jump(s) {
    setEmbed({ start: Math.floor(Number(s) || 0), auto: true });
    if (window.innerWidth < 1024) playerRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  const shownTranscript = useMemo(() => {
    const q = filter.trim().toLowerCase();
    return q ? transcript.filter((s) => String(s.text).toLowerCase().includes(q)) : transcript;
  }, [transcript, filter]);

  const ideas = useMemo(() => ["What are the main ideas in this video?", ...(knowledge?.concepts || []).slice(0, 3).map((c) => `Explain ${c.name}`)], [knowledge]);
  const reset = () => { setVideo(null); setUrl(""); setError(""); setThread([]); setResults(null); };

  const urlForm = (cls) => <form className={cls} onSubmit={analyze}>
    <input value={url} onChange={(e) => setUrl(e.target.value)} type="url" required aria-label="YouTube video URL" placeholder={video ? "Load another YouTube video…" : "Paste a YouTube link…"} />
    <button className="btn" disabled={loading}>{loading ? <><i className="spin" />Processing</> : video ? "Load" : "Analyze"}</button>
  </form>;

  return <div className="app">
    <header className="top">
      <button className="brand" onClick={reset} aria-label="INX home">INX<span>The Video Afterlife</span></button>
      {video && urlForm("url-form compact")}
    </header>
    {error && <div className="banner" role="alert"><span>{error}</span><button onClick={() => setError("")} aria-label="Dismiss">✕</button></div>}

    {showImport && <ImportPanel busy={loading} onImport={run} onClose={() => setShowImport(false)} />}

    {!video ? <main className="landing">
      <h1>Ask any YouTube video.</h1>
      <p>Paste a link. INX reads the transcript, lets you search it by meaning, and answers questions with the exact moments as evidence.</p>
      {urlForm("url-form big")}
      {loading && <p className="muted center"><i className="spin" /> Fetching the transcript and building the index. This can take a minute.</p>}
      <p className="hint">Works with videos that have captions. The video file is never downloaded.</p>
    </main> : <main className="workspace">
      <section className="video-pane" ref={playerRef}>
        <div className="player"><iframe title="YouTube video" src={`https://www.youtube.com/embed/${video.youtube_video_id}?start=${embed.start}${embed.auto ? "&autoplay=1" : ""}`} allow="autoplay; encrypted-media; picture-in-picture" allowFullScreen /></div>
        <h2 className="vtitle">{video.title || video.youtube_video_id}</h2>
        <div className="vmeta">
          <span className={`idx ${index.indexed ? "ready" : index.error ? "bad" : ""}`}>{index.indexed ? "Search ready" : index.loading ? "Preparing search…" : index.error ? "Search index failed" : "Search not ready"}</span>
          {!index.indexed && !index.loading && <button className="link" onClick={() => ensureIndex(video.youtube_video_id, true)}>Retry</button>}
          <a href={ytUrl(video.youtube_video_id, embed.start)} target="_blank" rel="noreferrer">Open on YouTube ↗</a>
        </div>
      </section>

      <section className="panel-wrap">
        <nav className="tabs" role="tablist">{TABS.map(([id, label]) => <button key={id} role="tab" aria-selected={tab === id} className={tab === id ? "on" : ""} onClick={() => setTab(id)}>{label}</button>)}</nav>

        {tab === "ask" && <div className="panel ask">
          <div className="scroll">
            <div className="measure">
              {!thread.length && <div className="empty"><h3>What do you want to know?</h3><p>Answers come only from this video’s transcript, with timestamps you can click.</p>
                <div className="chips">{ideas.map((s) => <button key={s} onClick={() => ask(s)}>{s}</button>)}</div></div>}
              {thread.map((t, i) => <Answer key={i} item={t} videoId={video.youtube_video_id} jump={jump} />)}
              <div ref={endRef} />
            </div>
          </div>
          <form className="composer" onSubmit={(e) => { e.preventDefault(); ask(); }}>
            <textarea rows="1" value={askText} onChange={(e) => setAskText(e.target.value)} aria-label="Ask a question about this video" placeholder="Ask a question about this video…"
              onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); ask(); } }} />
            <button className="btn" disabled={asking || !askText.trim()}>{asking ? <i className="spin" /> : "Ask"}</button>
          </form>
        </div>}

        {tab === "search" && <div className="panel"><div className="scroll"><div className="measure">
          <form className="url-form" onSubmit={search}>
            <input value={searchText} onChange={(e) => setSearchText(e.target.value)} aria-label="Search the video" placeholder="Search by meaning, e.g. how are weights adjusted?" />
            <button className="btn" disabled={searching || !searchText.trim()}>{searching ? <i className="spin" /> : "Search"}</button>
          </form>
          {!results && <p className="muted pad">Describe what you remember. Results are the best-matching transcript passages.</p>}
          {results && <p className="muted pad">{results.items.length ? `${results.items.length} passages for “${results.q}”` : `No passages found for “${results.q}”.`}</p>}
          {results?.items.map((x) => <article className="hit" key={x.chunk_index}>
            <div className="ev-meta">
              <button className="ts" onClick={() => jump(x.start_time)}>▶ {time(x.start_time)}–{time(x.end_time)}</button>
              <span className="muted" title={`Semantic ${pct(x.semantic_score)} · Keyword ${pct(x.keyword_score)}`}>{pct(x.score)} match</span>
              <a href={ytUrl(video.youtube_video_id, x.start_time)} target="_blank" rel="noreferrer">YouTube ↗</a>
            </div>
            <p>{x.text}</p>
            <small className="muted">Semantic {pct(x.semantic_score)} · Keyword {pct(x.keyword_score)}</small>
          </article>)}
        </div></div></div>}

        {tab === "transcript" && <div className="panel"><div className="scroll"><div className="measure">
          <div className="url-form"><input value={filter} onChange={(e) => setFilter(e.target.value)} aria-label="Filter transcript" placeholder="Filter transcript…" /><span className="count">{shownTranscript.length}/{transcript.length}</span></div>
          <ul className="tlist">{shownTranscript.map((s, i) => <li key={i}><button onClick={() => jump(s.start)}><span className="ts">{time(s.start)}</span><span>{s.text}</span></button></li>)}</ul>
          {!shownTranscript.length && <p className="muted pad">No matching lines.</p>}
        </div></div></div>}

        {tab === "outline" && <div className="panel"><div className="scroll"><div className="measure">
          {!knowledge && <p className="muted pad">No outline is available for this video.</p>}
          {mode === "extractive_fallback" && <p className="note warn block">Built from transcript sentences (AI unavailable). Check timestamps against the source.</p>}
          {knowledge?.structure?.length > 0 && <><h3 className="sec">Sections</h3><ol className="outline">{knowledge.structure.map((x, i) => <li key={i}><button onClick={() => jump(x.start_time)}><span className="ts">{time(x.start_time)}</span><span><b>{x.title}</b><em>{x.summary}</em></span></button></li>)}</ol></>}
          {knowledge?.topics?.length > 0 && <><h3 className="sec">Topics</h3><ul className="outline">{knowledge.topics.map((x, i) => <li key={i}><button onClick={() => jump(x.start_time)}><span className="ts">{time(x.start_time)}</span><span><b>{x.title}</b><em>{x.description}</em></span></button></li>)}</ul></>}
          {knowledge?.concepts?.length > 0 && <><h3 className="sec">Concepts</h3><div className="chips">{knowledge.concepts.map((x, i) => <button key={i} onClick={() => { setTab("ask"); ask(`Explain ${x.name}`); }}>{x.name}</button>)}</div></>}
        </div></div></div>}
      </section>
    </main>}
  </div>;
}

createRoot(document.getElementById("root")).render(<App />);