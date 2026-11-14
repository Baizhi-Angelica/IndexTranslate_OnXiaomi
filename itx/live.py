#!/usr/bin/env python3
"""Live subtitle bridge for the ITX overlay app.

    app (mic 16k s16le) --17322--> this script --VAD--> crispasr HTTP server
    app (TextView)      <--17321-- this script (JSON lines)

The crispasr server keeps the 2.6 GB index-echo model resident; each VAD segment
is posted to it as a WAV and the bilingual result is pushed to the overlay.
"""
import array
import io
import json
import os
import queue
import re
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import wave

TEXT_PORT = 17321
PCM_PORT = 17322
CRISPASR = os.path.expanduser("~/crispasr/build/bin/crispasr")
MODEL = os.path.expanduser("~/models/index-echo/index-echo-2b-q8_0.gguf")
MODEL_DIR = os.path.dirname(MODEL)
SR = 16000
FRAME = 1600  # 100 ms
THREADS = os.environ.get("ITX_THREADS", "7")
SERVER_PORT = 8899

# index-echo's --target-lang only accepts en/ja/es, but --ask replaces the whole
# instruction, and the model happily translates into the "other" language.
# That gives us zh->en AND en->zh with one model and one server.
#
# The rule is anchored on the *transcript*, not on the model's audio-language
# guess. "The other language" leaves it free to decide that Chinese speech is
# English and then "translate" Chinese into Chinese (the repeated-line failure);
# in one logged session 26 of 61 cues came back Chinese-only, and the trigger
# depended on the speaker's voice. Making line 2 conditional on the characters
# in line 1 fixed every failure in a 35-clip TTS regression set except one
# 0.3 s clip the model returns nothing for.
BIDIR_ASK = (
    "Output exactly two lines for each sentence, with no timestamps.\n"
    "Line 1: the transcript in the language actually spoken.\n"
    "Line 2: the translation into the other language. If line 1 contains Chinese "
    "characters, line 2 must be English. If line 1 is fully English, line 2 must be "
    "Chinese. Never repeat line 1 as line 2."
)
ASK = os.environ.get("ITX_ASK", BIDIR_ASK)

# VAD tuning (16-bit samples)
ABS_MIN_RMS = float(os.environ.get("ITX_VAD_MIN", "110"))
NOISE_RATIO = 2.2
SILENCE_MS = int(os.environ.get("ITX_SILENCE_MS", "550"))
MIN_SPEECH_MS = 400
MAX_SEG_MS = int(os.environ.get("ITX_MAX_SEG_MS", "5000"))
PREROLL_MS = 300

# Keep the newest speech only when the model falls behind: the queue is bounded
# and overflowing drops the OLDEST pending segment (showing a 15 s old line is
# worse than missing it). A segment that waited longer than ITX_STALE_S is
# skipped too, so a burst can never delay live captions indefinitely.
QUEUE_MAX = int(os.environ.get("ITX_QUEUE_MAX", "3"))
STALE_S = float(os.environ.get("ITX_STALE_S", "20"))
# Hard cap on generated tokens; a runaway decode otherwise costs tens of seconds.
MAX_NEW_TOKENS = int(os.environ.get("ITX_MAX_TOKENS", "160"))

log_lock = threading.Lock()


def log(*a):
    with log_lock:
        print(time.strftime("%H:%M:%S"), *a, flush=True)


class TextSink:
    """Connected overlay clients; pushes JSON lines to all of them."""

    def __init__(self):
        self.clients = set()
        self.lock = threading.Lock()
        self.had_client = False
        self.empty_since = None
        self.since = {}

    def add(self, sock):
        with self.lock:
            self.clients.add(sock)
            self.since[sock] = time.time()
            self.empty_since = None
            log("text client attached")
        self.send({"state": "listening"})

    def remove(self, sock):
        with self.lock:
            self.clients.discard(sock)
            started = self.since.pop(sock, None)
            # ignore transient probes (e.g. a TCP reachability check)
            if started is None or time.time() - started < 3.0:
                return
            self.had_client = True
            if not self.clients:
                self.empty_since = time.time()
        log("text client detached")

    def send(self, obj):
        data = (json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8")
        dead = []
        with self.lock:
            for s in list(self.clients):
                try:
                    s.sendall(data)
                except OSError:
                    dead.append(s)
            for s in dead:
                self.clients.discard(s)
                started = self.since.pop(s, None)
                if started is not None and time.time() - started >= 3.0:
                    self.had_client = True
                    if not self.clients:
                        self.empty_since = time.time()
        log("->", json.dumps(obj, ensure_ascii=False)[:90])


class Engine:
    def __init__(self):
        self.proc = None
        self.ready = False

    def start(self):
        log("starting crispasr server...")
        errlog = open(os.path.expanduser("~/itx/engine.log"), "ab")
        self.proc = subprocess.Popen(
            [CRISPASR, "--server", "-m", MODEL, "--backend", "index-echo",
             "--target-lang", "en", "--ask", ASK, "-t", THREADS,
             "--host", "127.0.0.1", "--port", str(SERVER_PORT), "--no-warmup"],
            cwd=MODEL_DIR, stdout=errlog, stderr=errlog,
        )
        for _ in range(120):
            if self.proc.poll() is not None:
                log("crispasr server exited with", self.proc.returncode)
                return False
            try:
                with socket.create_connection(("127.0.0.1", SERVER_PORT), timeout=1):
                    self.ready = True
                    log("crispasr server ready")
                    return True
            except OSError:
                time.sleep(1)
        return False

    def stop(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.ready = False

    def alive(self):
        try:
            with socket.create_connection(("127.0.0.1", SERVER_PORT), timeout=0.4):
                return True
        except OSError:
            return False

    def transcribe(self, pcm_bytes):
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(SR)
            w.writeframes(pcm_bytes)
        body = buf.getvalue()

        boundary = "----itxboundary0123456789"
        head = (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="file"; filename="seg.wav"\r\n'
            "Content-Type: audio/wav\r\n\r\n"
        ).encode()
        tail = (
            f"\r\n--{boundary}\r\n"
            'Content-Disposition: form-data; name="max_tokens"\r\n\r\n'
            f"{MAX_NEW_TOKENS}\r\n"
            f"--{boundary}--\r\n"
        ).encode()
        req = urllib.request.Request(
            f"http://127.0.0.1:{SERVER_PORT}/v1/audio/transcriptions",
            data=head + body + tail,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        )
        with urllib.request.urlopen(req, timeout=180) as r:
            raw = r.read()
        return json.loads(raw.decode("utf-8"))


TIMESTAMP_RE = re.compile(r"^\s*\[\d{1,2}:\d{2}(?:\.\d{1,2})?-\d{1,2}:\d{2}(?:\.\d{1,2})?\]\s*")


def _is_han(ch):
    return "\u4e00" <= ch <= "\u9fff"


def _has_letters(s):
    return any(_is_han(c) or (c.isalpha() and ord(c) < 128) for c in s)


def _script(s):
    """'zh' when Han characters dominate, 'en' for a Latin line, '?' otherwise."""
    han = sum(1 for c in s if _is_han(c))
    lat = sum(1 for c in s if c.isalpha() and ord(c) < 128)
    if han and han >= lat:
        return "zh"
    if lat:
        return "en"
    return "?"


def clean_lines(text):
    """Drop timestamps/blank lines and collapse the model's repeated line."""
    out = []
    for raw in (text or "").splitlines():
        ln = TIMESTAMP_RE.sub("", raw).strip()
        if not ln or not _has_letters(ln):
            continue
        if out and out[-1] == ln:
            continue
        out.append(ln)
    return out


def order_pairs(text):
    """One cue -> (main, sub).

    The prompt fixes the order -- line 1 is the transcript, the rest is its
    translation -- so the script of the words is not used to guess roles (the
    old code paired by script and could show the transcript as the translation).
    Several transcript/translation sentences in one cue are paired alternately.
    """
    lines = clean_lines(text)
    if not lines:
        return []
    if len(lines) == 1:
        return [(lines[0], "")]
    scripts = [_script(ln) for ln in lines]
    alternating = len(lines) % 2 == 0 and all(
        scripts[i] != scripts[i + 1] for i in range(0, len(lines), 2)
    )
    if alternating:
        return [(lines[i + 1], lines[i]) for i in range(0, len(lines), 2)]
    return [(" ".join(lines[1:]), lines[0])]


def wav_rms(frame_bytes):
    n = len(frame_bytes) // 2
    if n == 0:
        return 0.0
    total = 0
    for i in range(0, len(frame_bytes) - 1, 2):
        v = frame_bytes[i] | (frame_bytes[i + 1] << 8)
        if v >= 32768:
            v -= 65536
        total += v * v
    return (total / n) ** 0.5


GAIN = float(os.environ.get("ITX_GAIN", "8"))


def amplify(pcm, gain):
    """Digital gain with clipping (the phone's mic reaches us very quiet)."""
    if gain == 1.0:
        return pcm
    a = array.array("h")
    a.frombytes(pcm)
    for i in range(len(a)):
        v = int(a[i] * gain)
        if v > 32767:
            v = 32767
        elif v < -32768:
            v = -32768
        a[i] = v
    return a.tobytes()


class VAD:
    def __init__(self):
        self.noise = 200.0
        self.speaking = False
        self.segment = bytearray()
        self.preroll = bytearray()
        self.silence_ms = 0
        self.speech_ms = 0
        self.last_speech_len = 0

    def feed(self, frame):
        """Return a finished segment (bytes) or None."""
        rms = wav_rms(frame)
        if not self.speaking:
            self.noise = min(self.noise * 0.995 + rms * 0.005, 4000.0)
        thresh = max(ABS_MIN_RMS, self.noise * NOISE_RATIO)
        is_speech = rms > thresh

        if not self.speaking:
            self.preroll += frame
            if len(self.preroll) > (PREROLL_MS // 100) * len(frame):
                del self.preroll[: len(self.preroll) - (PREROLL_MS // 100) * len(frame)]
            if is_speech:
                self.speaking = True
                self.segment = bytearray(self.preroll)
                self.last_speech_len = len(self.segment)
                self.speech_ms = 100
                self.silence_ms = 0
            return None

        self.segment += frame
        if is_speech:
            self.speech_ms += 100
            self.silence_ms = 0
            self.last_speech_len = len(self.segment)
        else:
            self.silence_ms += 100

        seg_ms = len(self.segment) * 1000 // (SR * 2)
        if (self.silence_ms >= SILENCE_MS and self.speech_ms >= MIN_SPEECH_MS) or seg_ms >= MAX_SEG_MS:
            # keep 100 ms of the tail, drop the rest of the trailing silence
            cut = min(len(self.segment), self.last_speech_len + FRAME * 2)
            seg = bytes(self.segment[:cut])
            self.speaking = False
            self.segment = bytearray()
            self.speech_ms = 0
            self.silence_ms = 0
            self.preroll = bytearray()
            self.last_speech_len = 0
            return seg
        return None


class Worker(threading.Thread):
    def __init__(self, engine, sink):
        super().__init__(daemon=True)
        self.engine = engine
        self.sink = sink
        self.q = queue.Queue(maxsize=QUEUE_MAX)
        self.dropped = 0

    def submit(self, seg):
        """Enqueue with newest-first priority: when full, throw the OLDEST away."""
        item = (time.time(), seg)
        try:
            self.q.put_nowait(item)
            return
        except queue.Full:
            pass
        try:
            old_t, old = self.q.get_nowait()
            self.dropped += 1
            log(f"queue full: drop oldest {len(old)/(SR*2):.1f}s "
                f"(age {time.time()-old_t:.1f}s, total dropped {self.dropped})")
        except queue.Empty:
            pass
        try:
            self.q.put_nowait(item)
        except queue.Full:  # consumer raced us; keep the newest
            log("queue still full, dropping new segment")

    def run(self):
        while True:
            item = self.q.get()
            if item is None:
                return
            stamp, seg = item
            age = time.time() - stamp
            dur = len(seg) / (SR * 2)
            if age > STALE_S:
                self.dropped += 1
                log(f"drop stale segment: {dur:.1f}s waited {age:.1f}s "
                    f"(total dropped {self.dropped})")
                continue
            t0 = time.time()
            try:
                res = self.engine.transcribe(seg)
            except Exception as e:  # noqa: BLE001
                log("transcribe failed:", e)
                self.sink.send({"state": "error", "detail": str(e)[:80]})
                continue
            text = res.get("text", "")
            segments = res.get("segments") or []
            if segments:
                pairs = []
                for item in segments:
                    pairs.extend(order_pairs(item.get("text", "")))
            else:
                pairs = order_pairs(text)
            log(f"seg {dur:.1f}s -> {time.time()-t0:.1f}s, {len(segments)} cues, {len(pairs)} pair(s)"
                f" (queued {self.q.qsize()})")
            if not pairs or not any(sub for _, sub in pairs):
                log("raw:", (text or "").replace("\n", " | ")[:160])
            for main, sub in pairs:
                self.sink.send({"main": main, "sub": sub})
                time.sleep(0.15)


def engine_watchdog(engine, sink, stop):
    """Restart the crispasr server if it dies (e.g. killed by a racing starter)."""
    while not stop.is_set():
        time.sleep(4)
        if stop.is_set():
            break
        if not engine.alive():
            log("crispasr server lost, restarting")
            sink.send({"state": "loading"})
            try:
                engine.stop()
            except Exception:  # noqa: BLE001
                pass
            if engine.start():
                sink.send({"state": "listening"})
                log("crispasr server restarted")
            else:
                sink.send({"state": "error", "detail": "engine restart failed"})


def bind_retry(port, timeout=30.0):
    """Bind a listening socket, retrying while a previous instance still holds the port."""
    deadline = time.time() + timeout
    while True:
        s = socket.socket()
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("127.0.0.1", port))
            s.listen(2)
            s.settimeout(1.0)
            return s
        except OSError as e:
            s.close()
            if time.time() > deadline:
                raise
            log(f"port {port} busy ({e}), retrying")
            time.sleep(1.0)


def client_reader(c, sink, stop):
    c.settimeout(1.0)
    sink.add(c)
    try:
        buf = b""
        while not stop.is_set():
            try:
                data = c.recv(4096)
            except socket.timeout:
                continue
            except OSError:
                break
            if not data:
                break
            buf += data
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                try:
                    cmd = json.loads(line.decode("utf-8", "replace"))
                except ValueError:
                    continue
                if cmd.get("cmd") == "quit":
                    log("quit requested by app")
                    stop.set()
                    return
                if cmd.get("cmd") == "show":
                    sink.send({"state": "listening"})
    finally:
        sink.remove(c)
        try:
            c.close()
        except OSError:
            pass


def text_server(sink, stop):
    s = bind_retry(TEXT_PORT)
    while not stop.is_set():
        if (sink.had_client and sink.empty_since is not None
                and time.time() - sink.empty_since > 30):
            log("overlay app gone for 30s, shutting down")
            stop.set()
            return
        try:
            c, _ = s.accept()
        except socket.timeout:
            continue
        except OSError:
            break
        threading.Thread(target=client_reader, args=(c, sink, stop), daemon=True).start()
    s.close()


def save_segment(pcm):
    try:
        path = os.path.expanduser("~/itx/last_seg.wav")
        try:
            os.remove(path)
        except OSError:
            pass
        with wave.open(path, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(SR)
            w.writeframes(pcm)
        log(f"segment {len(pcm)//(SR*2):.1f}s rms={wav_rms(pcm):.0f} -> last_seg.wav")
    except Exception as e:  # noqa: BLE001
        log("save segment skipped:", e)


def run_text_server(sink, stop):
    try:
        text_server(sink, stop)
    except Exception as e:  # noqa: BLE001
        log("text server failed:", e)
        stop.set()


def main():
    stop = threading.Event()
    sink = TextSink()
    engine = Engine()
    try:
        if not engine.start():
            sink.send({"state": "error", "detail": "engine failed"})
            return 1
        worker = Worker(engine, sink)
        worker.start()
        threading.Thread(target=engine_watchdog, args=(engine, sink, stop), daemon=True).start()

        threading.Thread(target=run_text_server, args=(sink, stop), daemon=True).start()

        # PCM in
        ps = bind_retry(PCM_PORT)

        vad = VAD()
        sink.send({"state": "listening"})
        log("pcm listening on", PCM_PORT)
        dbg_frames = 0
        dbg_peak = 0.0
        while not stop.is_set():
            try:
                c, _ = ps.accept()
            except socket.timeout:
                continue
            log("pcm client attached")
            c.settimeout(1.0)
            buf = b""
            try:
                while not stop.is_set():
                    try:
                        data = c.recv(65536)
                    except socket.timeout:
                        continue
                    if not data:
                        break
                    buf += data
                    while len(buf) >= FRAME * 2:
                        frame, buf = buf[: FRAME * 2], buf[FRAME * 2:]
                        frame = amplify(frame, GAIN)
                        rms = wav_rms(frame)
                        if rms > dbg_peak:
                            dbg_peak = rms
                        seg = vad.feed(frame)
                        if seg:
                            save_segment(seg)
                            worker.submit(seg)
                        dbg_frames += 1
                        if dbg_frames % 50 == 0:
                            log(f"level peak={dbg_peak:.0f} noise={vad.noise:.0f}")
                            dbg_peak = 0
            except OSError as e:
                log("pcm error", e)
            finally:
                c.close()
                log("pcm client detached")
        worker.q.put(None)
        return 0
    finally:
        engine.stop()


if __name__ == "__main__":
    sys.exit(main())
