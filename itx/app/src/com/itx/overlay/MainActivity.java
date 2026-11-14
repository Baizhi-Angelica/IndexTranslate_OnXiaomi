package com.itx.overlay;

import android.app.Activity;
import android.content.Intent;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.provider.Settings;
import android.util.Log;

/**
 * Launcher: brings the app to the foreground (so a microphone foreground service may start),
 * makes sure the overlay permission is present, then starts the subtitle service and exits.
 * The Termux engine is started by the user from the overlay's guide panel.
 */
public class MainActivity extends Activity {
    private static final String TAG = "ITX";

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        if (Build.VERSION.SDK_INT >= 23 && !Settings.canDrawOverlays(this)) {
            Log.w(TAG, "overlay permission missing, opening settings");
            try {
                Intent i = new Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION,
                        Uri.parse("package:" + getPackageName()));
                i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                startActivity(i);
                finish();
                return;
            } catch (Throwable t) {
                Log.w(TAG, "cannot open overlay settings", t);
            }
        }

        Intent svc = new Intent(this, SubtitleService.class);
        svc.setAction(SubtitleService.ACTION_SHOW);
        if (Build.VERSION.SDK_INT >= 26) {
            startForegroundService(svc);
        } else {
            startService(svc);
        }
        new android.os.Handler(getMainLooper()).postDelayed(this::finish, 1200);
    }
}
