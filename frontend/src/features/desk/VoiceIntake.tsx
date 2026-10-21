"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api, type Attachment, type Capabilities, type WorkspaceInfo } from "@/lib/api";
import { Button, Notice } from "@/components/ui";

/* Minimal typing for the browser's speech recognition (not in lib.dom). */
interface SpeechRec {
  lang: string; continuous: boolean; interimResults: boolean;
  onresult: ((e: { resultIndex: number; results: ArrayLike<{ isFinal: boolean; 0: { transcript: string } }> }) => void) | null;
  onerror: ((e: { error: string }) => void) | null;
  onend: (() => void) | null;
  start(): void; stop(): void; abort(): void;
}
type SpeechRecCtor = new () => SpeechRec;
const speechCtor = (): SpeechRecCtor | null => {
  const w = window as unknown as { SpeechRecognition?: SpeechRecCtor; webkitSpeechRecognition?: SpeechRecCtor };
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
};

const FRIENDLY: Record<string, string> = {
  "not-allowed": "Microphone access was blocked. Allow it in the address bar, or type your request.",
  "service-not-allowed": "This browser won't let the page use speech recognition. Type your request instead.",
  "no-speech": "I didn't hear anything. Hold the button and try again, or type.",
  "audio-capture": "No microphone was found. Type your request instead.",
  network: "Speech recognition lost its connection. Try again, or type.",
};

interface Props {
  caseId: string;
  workspace?: WorkspaceInfo;
  caps: Capabilities | null;
  canWrite: boolean;
  initial?: string;
  onStart: (transcript: string) => Promise<void>;
}

export function VoiceIntake({ caseId, workspace, caps, canWrite, initial = "", onStart }: Props) {
  const [text, setText] = useState(initial);
  const [interim, setInterim] = useState("");
  const [recording, setRecording] = useState(false);
  const [busy, setBusy] = useState<"" | "transcribing" | "starting">("");
  const [error, setError] = useState("");
  const [sample, setSample] = useState(false);
  const [files, setFiles] = useState<Attachment[]>([]);
  const [canListen, setCanListen] = useState(true);

  const serverStt = !!(caps?.server_transcription && caps.ai_consent);
  const stream = useRef<MediaStream | null>(null);
  const audioCtx = useRef<AudioContext | null>(null);
  const analyser = useRef<AnalyserNode | null>(null);
  const recorder = useRef<MediaRecorder | null>(null);
  const chunks = useRef<Blob[]>([]);
  const recognition = useRef<SpeechRec | null>(null);
  const wanted = useRef(false); // true while the operator wants to be recording
  const discard = useRef(false);
  const pressedAt = useRef(0);
  const canvas = useRef<HTMLCanvasElement>(null);
  const raf = useRef(0);

  useEffect(() => { setCanListen(serverStt || !!speechCtor()); }, [serverStt]);

  // Waveform: real microphone levels, drawn as ink bars on a drafting baseline.
  const draw = useCallback(() => {
    const c = canvas.current;
    if (!c) return;
    const g = c.getContext("2d")!;
    const dpr = window.devicePixelRatio || 1;
    const w = c.clientWidth, h = c.clientHeight;
    if (c.width !== w * dpr) { c.width = w * dpr; c.height = h * dpr; }
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
    g.clearRect(0, 0, w, h);
    const bars = 56, gap = w / bars;
    const data = new Uint8Array(analyser.current?.frequencyBinCount ?? 0);
    analyser.current?.getByteFrequencyData(data);
    for (let i = 0; i < bars; i++) {
      const v = data.length ? data[Math.floor((i / bars) * data.length * 0.6)] / 255 : 0;
      const bh = Math.max(2, v * h * 0.95);
      g.fillStyle = v > 0.05 ? "#1f43d6" : "#b8b3a5";
      g.fillRect(i * gap + gap * 0.2, (h - bh) / 2, gap * 0.6, bh);
    }
    raf.current = requestAnimationFrame(draw);
  }, []);

  useEffect(() => {
    raf.current = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(raf.current);
  }, [draw]);

  const teardown = useCallback(() => {
    wanted.current = false;
    stream.current?.getTracks().forEach((t) => t.stop());
    stream.current = null;
    audioCtx.current?.close().catch(() => {});
    audioCtx.current = null;
    analyser.current = null;
    setRecording(false);
    setInterim("");
  }, []);

  useEffect(() => () => { recognition.current?.abort(); recorder.current?.state === "recording" && recorder.current.stop(); teardown(); }, [teardown]);

  async function start() {
    if (recording || !canWrite) return;
    setError("");
    discard.current = false;
    if (!serverStt && !speechCtor()) {
      setError("This browser can't turn speech into text. Type your request below, or open the desk in Chrome or Edge.");
      return;
    }
    try {
      stream.current = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch (e) {
      const denied = e instanceof DOMException && (e.name === "NotAllowedError" || e.name === "SecurityError");
      setError(denied ? FRIENDLY["not-allowed"] : FRIENDLY["audio-capture"]);
      return;
    }
    const ctx = new AudioContext();
    const src = ctx.createMediaStreamSource(stream.current);
    const an = ctx.createAnalyser();
    an.fftSize = 256;
    src.connect(an);
    audioCtx.current = ctx;
    analyser.current = an;
    wanted.current = true;
    setRecording(true);

    if (serverStt) {
      chunks.current = [];
      const rec = new MediaRecorder(stream.current);
      rec.ondataavailable = (e) => e.data.size && chunks.current.push(e.data);
      rec.onstop = async () => {
        const blob = new Blob(chunks.current, { type: rec.mimeType || "audio/webm" });
        teardown();
        if (discard.current || blob.size === 0) return;
        setBusy("transcribing");
        try {
          const r = await api.transcribe(caseId, blob);
          setText((t) => (t ? `${t.trimEnd()} ${r.transcript}` : r.transcript));
        } catch (err) {
          setError(err instanceof Error ? err.message : "Transcription failed. Type your request instead.");
        } finally { setBusy(""); }
      };
      recorder.current = rec;
      rec.start();
    } else {
      const Rec = speechCtor()!;
      const r = new Rec();
      r.lang = "en-IN";
      r.continuous = true;
      r.interimResults = true;
      r.onresult = (e) => {
        let live = "", final = "";
        for (let i = e.resultIndex; i < e.results.length; i++) {
          const piece = e.results[i][0].transcript;
          if (e.results[i].isFinal) final += piece; else live += piece;
        }
        if (final) setText((t) => (t ? `${t.trimEnd()} ${final.trim()}` : final.trim()));
        setInterim(live);
      };
      r.onerror = (e) => { setError(FRIENDLY[e.error] ?? "Speech recognition stopped unexpectedly. You can type instead."); wanted.current = false; };
      r.onend = () => { if (wanted.current) { try { r.start(); } catch { teardown(); } } else teardown(); }; // browsers stop after silence
      recognition.current = r;
      r.start();
    }
  }

  function stop(keep = true) {
    discard.current = !keep;
    wanted.current = false;
    if (serverStt && recorder.current?.state === "recording") recorder.current.stop();
    else if (recognition.current) { keep ? recognition.current.stop() : recognition.current.abort(); }
    if (!serverStt) setTimeout(teardown, 150);
  }

  // Push-to-talk: hold to record. A quick tap latches recording on; tap again to stop.
  const onPointerDown = () => {
    if (recording) { stop(); return; }
    pressedAt.current = Date.now();
    start();
  };
  const onPointerUp = () => {
    if (recording && pressedAt.current && Date.now() - pressedAt.current > 350) stop();
    pressedAt.current = 0;
  };
  const onKey = (e: React.KeyboardEvent) => {
    if ((e.key === " " || e.key === "Enter") && !e.repeat) { e.preventDefault(); recording ? stop() : start(); }
    if (e.key === "Escape" && recording) stop(false);
  };

  async function upload(list: FileList | null) {
    if (!list?.length) return;
    setError("");
    for (const f of Array.from(list)) {
      try {
        const att = await api.upload(caseId, f, "supporting");
        setFiles((cur) => [...cur, att]);
      } catch (e) { setError(e instanceof Error ? e.message : "Upload failed."); }
    }
  }

  async function begin() {
    setBusy("starting");
    setError("");
    try { await onStart(text.trim()); }
    catch (e) { setError(e instanceof Error ? e.message : "Could not start."); setBusy(""); }
  }

  return (
    <div className="space-y-5">
      <div className="grid gap-5 sm:grid-cols-[auto_1fr] sm:items-center">
        <button
          type="button" aria-pressed={recording} aria-label={recording ? "Stop recording" : "Hold to speak, or press Space to start"}
          disabled={!canWrite || busy !== ""}
          onPointerDown={onPointerDown} onPointerUp={onPointerUp} onPointerLeave={onPointerUp} onKeyDown={onKey}
          onContextMenu={(e) => e.preventDefault()}
          className={`relative grid h-24 w-24 shrink-0 touch-none select-none place-items-center rounded-full border-2 transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${recording ? "border-cobalt bg-cobalt text-sheet" : "border-ink bg-sheet text-ink hover:border-cobalt hover:text-cobalt"}`}
        >
          {recording && <span className="absolute inset-[-8px] animate-ping rounded-full border border-cobalt/50 motion-reduce:hidden" aria-hidden />}
          <svg width="30" height="30" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" aria-hidden>
            <rect x="9" y="3" width="6" height="12" rx="3" /><path d="M5 11a7 7 0 0 0 14 0M12 18v3" />
          </svg>
        </button>
        <div className="min-w-0">
          <canvas ref={canvas} className="h-14 w-full" role="img" aria-label={recording ? "Live microphone level" : "Microphone level, idle"} />
          <p className="mt-1 text-[0.9375rem] text-muted" aria-live="polite">
            {busy === "transcribing" ? "Turning your recording into text…"
              : recording ? "Listening. Release to stop, or press the button again."
              : canListen ? "Hold the button and speak. Tap once to keep it on."
              : "This browser can't transcribe speech. Type your request below."}
          </p>
        </div>
      </div>

      {recording && (
        <div className="flex gap-3">
          <Button variant="secondary" onClick={() => stop()}>Stop</Button>
          <Button variant="quiet" onClick={() => stop(false)}>Cancel</Button>
        </div>
      )}

      <div>
        <label htmlFor="transcript" className="mb-1 flex items-baseline justify-between text-[0.9375rem] font-medium">
          <span>What you said <span className="font-normal text-muted">(edit anything that is wrong)</span></span>
          {sample && <span className="text-[0.8125rem] font-normal text-ochre">Sample text</span>}
        </label>
        <textarea
          id="transcript" value={text} rows={6} maxLength={8000} disabled={!canWrite}
          onChange={(e) => { setText(e.target.value); setSample(false); }}
          placeholder="Describe the job in your own words. Include names, amounts and dates."
          className="w-full resize-y border border-rule bg-sheet px-4 py-3 font-display text-[1.125rem] leading-relaxed outline-none focus:border-cobalt"
        />
        {interim && <p className="mt-1 italic text-muted" aria-hidden>{interim}</p>}
        <div className="mt-2 flex flex-wrap items-center gap-x-5 gap-y-2 text-[0.9375rem]">
          {recording === false && text && <button type="button" className="underline decoration-rule underline-offset-4 hover:text-cobalt" onClick={() => { setText(""); setSample(false); start(); }}>Record again</button>}
          {workspace && (
            <button type="button" className="underline decoration-rule underline-offset-4 hover:text-cobalt"
              onClick={() => { setText(workspace.example_prompt); setSample(true); }}>
              Use a sample dictation
            </button>
          )}
          <label className="cursor-pointer underline decoration-rule underline-offset-4 hover:text-cobalt">
            Attach notes
            <input type="file" multiple accept=".txt,.docx,.pdf,.csv,.png,.jpg,.jpeg" className="sr-only" onChange={(e) => { upload(e.target.files); e.target.value = ""; }} />
          </label>
          <span className="text-muted">{text.length}/8000</span>
        </div>
        {files.length > 0 && (
          <ul className="mt-2 space-y-1 text-[0.9375rem]">
            {files.map((f) => <li key={f.id} className="text-ink-2">Attached: {f.name}</li>)}
          </ul>
        )}
      </div>

      {error && <Notice kind="error">{error}</Notice>}
      {!serverStt && (
        <p className="max-w-[62ch] text-[0.8125rem] text-muted">
          Speech is transcribed by your browser. Some browsers send the audio to their vendor&apos;s speech service. Typing sends nothing anywhere.
          {caps && caps.llm_provider !== "demo" && !caps.ai_consent && " Your business has not agreed to send text to an AI service, so built-in rules read your request instead."}
        </p>
      )}
      <div>
        <Button onClick={begin} busy={busy === "starting"} disabled={!canWrite || text.trim().length < 3 || recording || busy === "transcribing"}>
          Prepare documents
        </Button>
        <p className="mt-2 text-[0.8125rem] text-muted">This reads your request and builds a draft. Nothing is exported or sent until you approve it.</p>
      </div>
    </div>
  );
}
