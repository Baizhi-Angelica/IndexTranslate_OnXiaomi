package com.itx.overlay;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.ClipData;
import android.content.ClipboardManager;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.graphics.PixelFormat;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.media.AudioFormat;
import android.media.AudioRecord;
import android.media.MediaRecorder;
import android.os.Build;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;
import android.os.PowerManager;
import android.provider.Settings;
import android.util.Log;
import android.view.Gravity;
import android.view.View;
import android.view.WindowManager;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.TextView;

import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.io.OutputStreamWriter;
import java.io.Writer;
import java.net.InetSocketAddress;
import java.net.Socket;
import java.nio.charset.StandardCharsets;

/**
 * Foreground service owning the subtitle overlay, the microphone capture and the guide panel
 * that tells the user which Termux command to run.
 *
 * Termux side is started by hand (no root involved):
 *   bash ~/itx/start.sh    (engine)
 *   bash ~/itx/stop.sh     (cleanup)
 */
public class SubtitleService extends Service {
    private static final String TAG = "ITX";
    public static final String ACTION_SHOW = "com.itx.overlay.SHOW";
    public static final String ACTION_HIDE = "com.itx.overlay.HIDE";
    public static final String ACTION_STOP = "com.itx.overlay.STOP";

    private static final int TEXT_PORT = 17321;
    private static final int PCM_PORT = 17322;
    private static final int SAMPLE_RATE = 16000;
    private static final int NOTIF_ID = 42;
    private static final String CHANNEL = "itx_overlay";

    private static final String START_CMD = "bash ~/itx/start.sh";
    private static final String STOP_CMD = "bash ~/itx/stop.sh";

    private final Handler ui = new Handler(Looper.getMainLooper());

    private WindowManager wm;
    private LinearLayout subtitleRoot;
    private LinearLayout controlRoot;
    private LinearLayout guideBox;
    private LinearLayout subtitleBox;
    private TextView guideTitle;
    private TextView guideCmd;
    private Button copyBtn;
    private Button closeBtn;
    private TextView prevEnView;
    private TextView prevZhView;
    private TextView enView;
    private TextView zhView;
    private TextView statusView;

    private PowerManager.WakeLock wakeLock;

    private volatile boolean running = true;
    private volatile boolean windowsShown = false;
    private volatile boolean connected = false;
    private volatile boolean exiting = false;

    private volatile Socket textSock;
    private volatile Writer textOut;
    private volatile Socket pcmSock;
    private volatile OutputStream pcmOut;

    private AudioRecord recorder;
    private Thread audioThread;
    private Thread textThread;

    private String lastEn = "";
    private String lastZh = "";

    // ---------------------------------------------------------------- lifecycle

    @Override
    public void onCreate() {
        super.onCreate();
        wm = (WindowManager) getSystemService(Context.WINDOW_SERVICE);
        createChannel();
        startForegroundCompat();
        PowerManager pm = (PowerManager) getSystemService(Context.POWER_SERVICE);
        if (pm != null) {
            wakeLock = pm.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "itx:subtitle");
            wakeLock.setReferenceCounted(false);
            wakeLock.acquire();
        }
        startNetworking();
        startRecording();
        showOverlay();
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        String action = intent == null ? ACTION_SHOW : intent.getAction();
        Log.i(TAG, "onStartCommand " + action);
        if (ACTION_STOP.equals(action)) {
            sendCommand("quit");
            stopSelf();
            return START_NOT_STICKY;
        }
        if (ACTION_HIDE.equals(action)) {
            ui.post(this::hideOverlay);
            return START_STICKY;
        }
        if (!windowsShown) {
            showOverlay();
        }
        return START_STICKY;
    }

    @Override
    public void onDestroy() {
        running = false;
        ui.post(this::hideOverlay);
        stopRecording();
        closeSockets();
        if (wakeLock != null && wakeLock.isHeld()) {
            wakeLock.release();
        }
        super.onDestroy();
    }

    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }

    // ---------------------------------------------------------------- notification

    private void createChannel() {
        if (Build.VERSION.SDK_INT >= 26) {
            NotificationManager nm = (NotificationManager) getSystemService(Context.NOTIFICATION_SERVICE);
            NotificationChannel ch = new NotificationChannel(CHANNEL, "实时字幕", NotificationManager.IMPORTANCE_LOW);
            nm.createNotificationChannel(ch);
        }
    }

    private PendingIntent contentIntent() {
        Intent i = new Intent(this, MainActivity.class);
        i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        int flags = PendingIntent.FLAG_UPDATE_CURRENT;
        if (Build.VERSION.SDK_INT >= 23) {
            flags |= PendingIntent.FLAG_IMMUTABLE;
        }
        return PendingIntent.getActivity(this, 0, i, flags);
    }

    private void startForegroundCompat() {
        Notification.Builder b = Build.VERSION.SDK_INT >= 26
                ? new Notification.Builder(this, CHANNEL)
                : new Notification.Builder(this);
        b.setSmallIcon(android.R.drawable.ic_btn_speak_now)
                .setContentTitle("ITX 实时字幕")
                .setContentText("点按可重新显示")
                .setOngoing(true)
                .setContentIntent(contentIntent());
        startForeground(NOTIF_ID, b.build());
    }

    // ---------------------------------------------------------------- overlay

    private int dp(float v) {
        return (int) (v * getResources().getDisplayMetrics().density + 0.5f);
    }

    private void showOverlay() {
        ui.post(() -> {
            if (windowsShown) {
                return;
            }
            if (Build.VERSION.SDK_INT >= 23 && !Settings.canDrawOverlays(this)) {
                Log.e(TAG, "no overlay permission");
                return;
            }
            try {
                addSubtitleWindow();
                addControlWindow();
                windowsShown = true;
                applyConnectedUi(connected);
                Log.i(TAG, "overlay shown (connected=" + connected + ")");
            } catch (Throwable t) {
                Log.e(TAG, "failed to add overlay", t);
            }
        });
    }

    private void hideOverlay() {
        if (subtitleRoot != null) {
            try {
                wm.removeView(subtitleRoot);
            } catch (Throwable ignored) {
            }
            subtitleRoot = null;
        }
        if (controlRoot != null) {
            try {
                wm.removeView(controlRoot);
            } catch (Throwable ignored) {
            }
            controlRoot = null;
        }
        windowsShown = false;
    }

    private WindowManager.LayoutParams overlayParams(int w, int h) {
        int type = Build.VERSION.SDK_INT >= 26
                ? WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY
                : WindowManager.LayoutParams.TYPE_PHONE;
        WindowManager.LayoutParams lp = new WindowManager.LayoutParams(
                w, h, type,
                WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE
                        | WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN
                        | WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON,
                PixelFormat.TRANSLUCENT);
        lp.alpha = 1.0f;
        if (Build.VERSION.SDK_INT >= 28) {
            lp.layoutInDisplayCutoutMode =
                    WindowManager.LayoutParams.LAYOUT_IN_DISPLAY_CUTOUT_MODE_SHORT_EDGES;
        }
        return lp;
    }

    private void addSubtitleWindow() {
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setBackgroundColor(Color.WHITE);
        root.setPadding(dp(20), dp(8), dp(20), dp(6));

        // ---- guide (shown until the Termux engine connects) ----
        guideBox = new LinearLayout(this);
        guideBox.setOrientation(LinearLayout.VERTICAL);
        guideBox.setGravity(Gravity.CENTER);
        guideBox.setLayoutParams(new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, 0, 1f));

        guideTitle = new TextView(this);
        guideTitle.setTextColor(Color.BLACK);
        guideTitle.setTextSize(26f);
        guideTitle.setGravity(Gravity.CENTER);
        guideTitle.setTypeface(Typeface.create(Typeface.SANS_SERIF, Typeface.BOLD));
        guideTitle.setText("在 Termux 中运行下面的命令启动引擎");
        guideBox.addView(guideTitle, new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT));

        guideCmd = new TextView(this);
        guideCmd.setTextColor(Color.BLACK);
        guideCmd.setTextSize(22f);
        guideCmd.setGravity(Gravity.CENTER);
        guideCmd.setTypeface(Typeface.MONOSPACE);
        guideCmd.setTextIsSelectable(true);
        guideCmd.setText(START_CMD);
        LinearLayout.LayoutParams cmdLp = new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT);
        cmdLp.topMargin = dp(14);
        guideBox.addView(guideCmd, cmdLp);

        LinearLayout guideBtns = new LinearLayout(this);
        guideBtns.setOrientation(LinearLayout.HORIZONTAL);
        guideBtns.setGravity(Gravity.CENTER);
        LinearLayout.LayoutParams gbLp = new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.WRAP_CONTENT, LinearLayout.LayoutParams.WRAP_CONTENT);
        gbLp.topMargin = dp(18);
        guideBox.addView(guideBtns, gbLp);

        copyBtn = new Button(this);
        copyBtn.setText("复制命令");
        styleButton(copyBtn, dp(140), dp(44));
        copyBtn.setOnClickListener(v -> {
            copyToClipboard(guideCmd.getText().toString());
            setStatus("● 已复制，去 Termux 粘贴并回车");
        });
        guideBtns.addView(copyBtn);

        closeBtn = new Button(this);
        closeBtn.setText("关闭");
        styleButton(closeBtn, dp(100), dp(44));
        closeBtn.setVisibility(View.GONE);
        LinearLayout.LayoutParams clLp = new LinearLayout.LayoutParams(dp(100), dp(44));
        clLp.leftMargin = dp(10);
        guideBtns.addView(closeBtn, clLp);
        closeBtn.setOnClickListener(v -> {
            stopForeground(true);
            stopSelf();
            ui.postDelayed(() -> System.exit(0), 600);
        });

        root.addView(guideBox);

        // ---- subtitles ----
        subtitleBox = new LinearLayout(this);
        subtitleBox.setOrientation(LinearLayout.VERTICAL);
        subtitleBox.setGravity(Gravity.CENTER);
        subtitleBox.setVisibility(View.GONE);
        subtitleBox.setLayoutParams(new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, 0, 1f));

        prevEnView = new TextView(this);
        prevEnView.setTextColor(Color.rgb(90, 90, 90));
        prevEnView.setTextSize(24f);
        prevEnView.setGravity(Gravity.CENTER);
        prevEnView.setMaxLines(2);
        LinearLayout.LayoutParams prevEnLp = new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT);
        prevEnLp.bottomMargin = dp(8);
        subtitleBox.addView(prevEnView, prevEnLp);

        prevZhView = new TextView(this);
        prevZhView.setTextColor(Color.rgb(140, 140, 140));
        prevZhView.setTextSize(14f);
        prevZhView.setGravity(Gravity.CENTER);
        prevZhView.setMaxLines(1);
        LinearLayout.LayoutParams prevZhLp = new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT);
        prevZhLp.bottomMargin = dp(14);
        subtitleBox.addView(prevZhView, prevZhLp);

        enView = new TextView(this);
        enView.setTextColor(Color.BLACK);
        enView.setTextSize(46f);
        enView.setTypeface(Typeface.create(Typeface.SANS_SERIF, Typeface.BOLD));
        enView.setGravity(Gravity.CENTER);
        enView.setMaxLines(3);
        subtitleBox.addView(enView, new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT));

        zhView = new TextView(this);
        zhView.setTextColor(Color.BLACK);
        zhView.setTextSize(21f);
        zhView.setGravity(Gravity.CENTER);
        zhView.setMaxLines(3);
        LinearLayout.LayoutParams zhLp = new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT);
        zhLp.topMargin = dp(12);
        subtitleBox.addView(zhView, zhLp);

        root.addView(subtitleBox);

        statusView = new TextView(this);
        statusView.setTextColor(Color.rgb(150, 150, 150));
        statusView.setTextSize(11f);
        statusView.setGravity(Gravity.CENTER);
        statusView.setText("● 等待 Termux 启动引擎…");
        root.addView(statusView, new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT));

        WindowManager.LayoutParams lp = overlayParams(
                WindowManager.LayoutParams.MATCH_PARENT,
                WindowManager.LayoutParams.MATCH_PARENT);
        lp.flags |= WindowManager.LayoutParams.FLAG_LAYOUT_NO_LIMITS;
        lp.format = PixelFormat.OPAQUE;
        lp.gravity = Gravity.TOP | Gravity.START;
        wm.addView(root, lp);
        subtitleRoot = root;
    }

    private void addControlWindow() {
        LinearLayout bar = new LinearLayout(this);
        bar.setOrientation(LinearLayout.HORIZONTAL);

        Button hide = new Button(this);
        hide.setText("隐藏");
        styleButton(hide, dp(56), dp(32));
        hide.setOnClickListener(v -> hideOverlay());
        bar.addView(hide, new LinearLayout.LayoutParams(dp(56), dp(32)));

        Button quit = new Button(this);
        quit.setText("退出");
        styleButton(quit, dp(56), dp(32));
        LinearLayout.LayoutParams lp2 = new LinearLayout.LayoutParams(dp(56), dp(32));
        lp2.leftMargin = dp(6);
        bar.addView(quit, lp2);
        quit.setOnClickListener(v -> doExit());

        WindowManager.LayoutParams lp = overlayParams(
                WindowManager.LayoutParams.WRAP_CONTENT,
                WindowManager.LayoutParams.WRAP_CONTENT);
        lp.gravity = Gravity.TOP | Gravity.RIGHT;
        lp.x = dp(6);
        lp.y = dp(46);
        wm.addView(bar, lp);
        controlRoot = bar;
    }

    private void styleButton(Button b, int w, int h) {
        b.setTextColor(Color.WHITE);
        b.setTextSize(12f);
        b.setAllCaps(false);
        b.setPadding(0, 0, 0, 0);
        b.setMinHeight(0);
        b.setMinWidth(0);
        GradientDrawable bg = new GradientDrawable();
        bg.setColor(Color.argb(150, 30, 30, 30));
        bg.setCornerRadius(dp(10));
        b.setBackground(bg);
        b.setLayoutParams(new LinearLayout.LayoutParams(w, h));
    }

    private void copyToClipboard(String text) {
        try {
            ClipboardManager cm = (ClipboardManager) getSystemService(Context.CLIPBOARD_SERVICE);
            cm.setPrimaryClip(ClipData.newPlainText("itx command", text));
        } catch (Throwable t) {
            Log.w(TAG, "clipboard failed", t);
        }
    }

    /** Show either the subtitles (engine connected) or the guide panel. */
    private void setConnected(boolean on) {
        connected = on;
        ui.post(() -> applyConnectedUi(on));
    }

    private void applyConnectedUi(boolean on) {
        if (guideBox == null || subtitleBox == null) {
            return;
        }
        guideBox.setVisibility(on ? View.GONE : View.VISIBLE);
        subtitleBox.setVisibility(on ? View.VISIBLE : View.GONE);
        if (statusView != null && !exiting) {
            statusView.setText(on ? "● 聆听中" : "● 等待 Termux 启动引擎…");
        }
    }

    private void doExit() {
        if (exiting) {
            return;
        }
        exiting = true;
        Log.i(TAG, "exit pressed");
        sendCommand("quit");
        stopRecording();
        closeSockets();
        // engine stops itself via the quit command; show the manual fallback anyway
        copyToClipboard(STOP_CMD);
        ui.post(() -> {
            setConnected(false);
            if (guideTitle != null) {
                guideTitle.setText("已通知引擎退出。若 Termux 里还有进程，请运行：");
            }
            if (guideCmd != null) {
                guideCmd.setText(STOP_CMD);
            }
            if (closeBtn != null) {
                closeBtn.setVisibility(View.VISIBLE);
            }
            if (statusView != null) {
                statusView.setText("● 已复制停止命令，点「关闭」退出悬浮窗");
            }
        });
    }

    // ---------------------------------------------------------------- networking

    private void startNetworking() {
        textThread = new Thread(this::textLoop, "itx-text");
        textThread.setDaemon(true);
        textThread.start();
    }

    private void textLoop() {
        while (running) {
            Socket s = null;
            try {
                s = new Socket();
                s.connect(new InetSocketAddress("127.0.0.1", TEXT_PORT), 800);
                s.setTcpNoDelay(true);
                textSock = s;
                textOut = new OutputStreamWriter(s.getOutputStream(), StandardCharsets.UTF_8);
                BufferedReader in = new BufferedReader(
                        new InputStreamReader(s.getInputStream(), StandardCharsets.UTF_8));
                setConnected(true);
                setStatus("● 聆听中");
                String line;
                while (running && (line = in.readLine()) != null) {
                    handleLine(line);
                }
            } catch (Throwable t) {
                // engine not up yet
            } finally {
                closeQuietly(s);
                textSock = null;
                textOut = null;
                if (running && !exiting) {
                    setConnected(false);
                    setStatus("● 等待 Termux 启动引擎…");
                    sleep(1000);
                }
            }
        }
    }

    private void handleLine(String line) {
        try {
            JSONObject o = new JSONObject(line);
            if (o.has("state")) {
                String st = o.optString("state", "");
                if ("listening".equals(st)) {
                    setConnected(true);
                    setStatus("● 聆听中");
                } else if ("loading".equals(st)) {
                    setStatus("● 模型加载中…");
                } else if ("error".equals(st)) {
                    setStatus("● 出错：" + o.optString("detail", ""));
                }
            }
            if (o.has("en") || o.has("zh")) {
                String newEn = o.optString("en", lastEn);
                String newZh = o.optString("zh", lastZh);
                if (newEn.equals(lastEn) && newZh.equals(lastZh)) {
                    return;
                }
                final String pEn = lastEn;
                final String pZh = lastZh;
                lastEn = newEn;
                lastZh = newZh;
                ui.post(() -> {
                    if (prevEnView != null) {
                        prevEnView.setText(pEn);
                        prevEnView.setVisibility(pEn.isEmpty() ? View.GONE : View.VISIBLE);
                    }
                    if (prevZhView != null) {
                        prevZhView.setText(pZh);
                        prevZhView.setVisibility(pZh.isEmpty() ? View.GONE : View.VISIBLE);
                    }
                    if (enView != null) {
                        enView.setText(lastEn);
                    }
                    if (zhView != null) {
                        zhView.setText(lastZh);
                    }
                });
            }
        } catch (Throwable t) {
            Log.w(TAG, "bad line: " + line, t);
        }
    }

    private void setStatus(String s) {
        ui.post(() -> {
            if (statusView != null) {
                statusView.setText(s);
            }
        });
    }

    private void sendCommand(String cmd) {
        Writer w = textOut;
        if (w == null) {
            return;
        }
        try {
            w.write("{\"cmd\":\"" + cmd + "\"}\n");
            w.flush();
        } catch (Throwable ignored) {
        }
    }

    // ---------------------------------------------------------------- microphone

    private void startRecording() {
        if (Build.VERSION.SDK_INT >= 23
                && checkSelfPermission(android.Manifest.permission.RECORD_AUDIO)
                != PackageManager.PERMISSION_GRANTED) {
            Log.e(TAG, "RECORD_AUDIO not granted");
            setStatus("● 缺少录音权限");
            return;
        }
        audioThread = new Thread(this::audioLoop, "itx-audio");
        audioThread.setDaemon(true);
        audioThread.start();
    }

    private boolean openRecorder() {
        int min = AudioRecord.getMinBufferSize(SAMPLE_RATE, AudioFormat.CHANNEL_IN_MONO,
                AudioFormat.ENCODING_PCM_16BIT);
        int buf = Math.max(min * 4, 16000);
        int[] sources = new int[]{MediaRecorder.AudioSource.MIC,
                MediaRecorder.AudioSource.VOICE_RECOGNITION,
                MediaRecorder.AudioSource.DEFAULT};
        for (int src : sources) {
            try {
                AudioRecord r = new AudioRecord(src, SAMPLE_RATE, AudioFormat.CHANNEL_IN_MONO,
                        AudioFormat.ENCODING_PCM_16BIT, buf);
                if (r.getState() == AudioRecord.STATE_INITIALIZED) {
                    r.startRecording();
                    if (r.getRecordingState() == AudioRecord.RECORDSTATE_RECORDING) {
                        recorder = r;
                        Log.i(TAG, "recorder started, source=" + src);
                        return true;
                    }
                }
                r.release();
            } catch (Throwable t) {
                Log.w(TAG, "recorder source " + src + " failed", t);
            }
        }
        return false;
    }

    private void audioLoop() {
        byte[] buf = new byte[3200];
        while (running) {
            if (recorder == null && !openRecorder()) {
                setStatus("● 无法打开麦克风");
                sleep(2000);
                continue;
            }
            if (pcmOut == null) {
                try {
                    Socket s = new Socket();
                    s.connect(new InetSocketAddress("127.0.0.1", PCM_PORT), 800);
                    s.setTcpNoDelay(true);
                    pcmSock = s;
                    pcmOut = s.getOutputStream();
                } catch (Throwable t) {
                    sleep(800);
                    continue;
                }
            }
            int n;
            try {
                n = recorder.read(buf, 0, buf.length);
            } catch (Throwable t) {
                n = -1;
            }
            if (n <= 0) {
                sleep(20);
                continue;
            }
            try {
                pcmOut.write(buf, 0, n);
                pcmOut.flush();
            } catch (Throwable t) {
                closeQuietly(pcmSock);
                pcmSock = null;
                pcmOut = null;
            }
        }
    }

    private void stopRecording() {
        AudioRecord r = recorder;
        recorder = null;
        if (r != null) {
            try {
                r.stop();
            } catch (Throwable ignored) {
            }
            try {
                r.release();
            } catch (Throwable ignored) {
            }
        }
    }

    private void closeSockets() {
        closeQuietly(textSock);
        closeQuietly(pcmSock);
        textSock = null;
        pcmSock = null;
        pcmOut = null;
        textOut = null;
    }

    private static void closeQuietly(java.io.Closeable c) {
        if (c != null) {
            try {
                c.close();
            } catch (Throwable ignored) {
            }
        }
    }

    private static void sleep(long ms) {
        try {
            Thread.sleep(ms);
        } catch (InterruptedException ignored) {
            Thread.currentThread().interrupt();
        }
    }
}
