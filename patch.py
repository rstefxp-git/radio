# Appliqué par le workflow après "npx cap sync android" :
# lecture écran éteint + lecteur multimédia sur l'écran verrouillé + flux http autorisés.
import json
import os

CFG = "android/app/src/main/assets/capacitor.config.json"
PKG = json.load(open(CFG, encoding="utf-8"))["appId"]
APP = "android/app/src/main/java/" + PKG.replace(".", "/")

# 1. WebView toujours "visible" : l'extinction de l'écran ne met plus la lecture en pause
f = "node_modules/@capacitor/android/capacitor/src/main/java/com/getcapacitor/CapacitorWebView.java"
s = open(f, encoding="utf-8").read()
if "onWindowVisibilityChanged" not in s:
    add = """
    @Override
    protected void onWindowVisibilityChanged(int visibility) {
        super.onWindowVisibilityChanged(android.view.View.VISIBLE);
    }
"""
    i = s.rstrip().rfind("}")
    s = s[:i] + add + "}\n"
    open(f, "w", encoding="utf-8").write(s)

# 2. Service de lecture : session multimédia + notification (écran verrouillé) + verrou CPU
open(APP + "/KeepAliveService.java", "w", encoding="utf-8").write("""package %s;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Intent;
import android.content.pm.ServiceInfo;
import android.graphics.Bitmap;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.graphics.BitmapFactory;
import android.graphics.drawable.Icon;
import android.media.MediaMetadata;
import android.media.session.MediaSession;
import android.media.session.PlaybackState;
import android.os.Build;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;
import android.os.PowerManager;
import android.webkit.WebView;
import android.widget.Toast;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;

public class KeepAliveService extends Service {
    // état partagé avec MainActivity (renseigné par la page)
    static volatile WebView web;
    static volatile KeepAliveService inst;
    static volatile String title = "Lecteur";
    static volatile String channel = "";
    static volatile String vid = "";
    static volatile boolean playing = false;
    static volatile long posMs = 0;
    static volatile long durMs = 0;
    static volatile Bitmap art = null;

    private MediaSession session;
    private PowerManager.WakeLock lock;
    private final Handler handler = new Handler(Looper.getMainLooper());
    private final Runnable idleStop = new Runnable() {
        @Override
        public void run() {
            stopSelf();
        }
    };

    @Override
    public void onCreate() {
        super.onCreate();
        inst = this;
        session = new MediaSession(this, "lecteur");
        session.setFlags(MediaSession.FLAG_HANDLES_MEDIA_BUTTONS | MediaSession.FLAG_HANDLES_TRANSPORT_CONTROLS);
        session.setCallback(new MediaSession.Callback() {
            @Override
            public void onPlay() {
                command("play");
            }

            @Override
            public void onPause() {
                command("pause");
            }

            @Override
            public void onSkipToNext() {
                command("next");
            }

            @Override
            public void onSkipToPrevious() {
                command("prev");
            }

            @Override
            public void onSeekTo(long pos) {
                seek(pos / 1000.0);
            }
        });
        session.setActive(true);
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        String a = intent != null ? intent.getAction() : null;
        if (a != null) {
            command(a);
        }
        update();
        return START_NOT_STICKY;
    }

    // ---- commandes vers la page ----
    static void js(final String code) {
        final WebView w = web;
        if (w != null) {
            w.post(new Runnable() {
                @Override
                public void run() {
                    w.evaluateJavascript(code, null);
                }
            });
        }
    }

    static void command(String a) {
        String act = a;
        if (act.equals("toggle")) {
            act = playing ? "pause" : "play";
        }
        js("window.__mc&&__mc('" + act + "')");
    }

    static void seek(double sec) {
        js("window.__mc&&__mc('seek'," + sec + ")");
    }

    // ---- métadonnées ----
    static void setMeta(String t, String c, final String artUrl) {
        title = t;
        channel = c;
        posMs = 0;
        durMs = 0;
        if (!artUrl.equals(vid)) {
            vid = artUrl;
            art = null;
            if (artUrl.startsWith("tile:")) {
                art = tile(artUrl);
            } else if (artUrl.startsWith("http")) {
                new Thread(new Runnable() {
                    @Override
                    public void run() {
                        try {
                            HttpURLConnection h = (HttpURLConnection) new URL(artUrl).openConnection();
                            h.setConnectTimeout(5000);
                            h.setReadTimeout(5000);
                            InputStream in = h.getInputStream();
                            Bitmap bm = BitmapFactory.decodeStream(in);
                            in.close();
                            if (artUrl.equals(vid)) {
                                art = bm;
                                KeepAliveService s = inst;
                                if (s != null) {
                                    s.refreshOnMain();
                                }
                            }
                        } catch (Exception e) {
                            // pochette facultative
                        }
                    }
                }).start();
            }
        }
        KeepAliveService s = inst;
        if (s != null) {
            s.refreshOnMain();
        }
    }

    // pochette générée : "tile:NC1:#b8326e" -> carré de couleur avec l'abréviation
    static Bitmap tile(String spec) {
        try {
            String[] p = spec.split(":");
            Bitmap bm = Bitmap.createBitmap(256, 256, Bitmap.Config.ARGB_8888);
            Canvas cv = new Canvas(bm);
            cv.drawColor(Color.parseColor(p.length > 2 ? p[2] : "#2f6fd0"));
            Paint pt = new Paint(Paint.ANTI_ALIAS_FLAG);
            pt.setColor(Color.WHITE);
            pt.setTextAlign(Paint.Align.CENTER);
            pt.setFakeBoldText(true);
            pt.setTextSize(p[1].length() > 3 ? 70 : 96);
            cv.drawText(p[1], 128, 128 + pt.getTextSize() / 3, pt);
            return bm;
        } catch (Exception e) {
            return null;
        }
    }

    void refreshOnMain() {
        handler.post(new Runnable() {
            @Override
            public void run() {
                update();
            }
        });
    }

    void toast(final String m) {
        handler.post(new Runnable() {
            @Override
            public void run() {
                Toast.makeText(getApplicationContext(), m, Toast.LENGTH_SHORT).show();
            }
        });
    }

    // ---- session + notification ----
    private void update() {
        try {
            doUpdate();
        } catch (Throwable t) {
            toast("Lecteur : erreur " + t);
            stopSelf();
        }
    }

    private void doUpdate() {
        MediaMetadata.Builder mb = new MediaMetadata.Builder()
            .putString(MediaMetadata.METADATA_KEY_TITLE, title)
            .putString(MediaMetadata.METADATA_KEY_ARTIST, channel);
        if (durMs > 0) {
            mb.putLong(MediaMetadata.METADATA_KEY_DURATION, durMs);
        }
        if (art != null) {
            mb.putBitmap(MediaMetadata.METADATA_KEY_ALBUM_ART, art);
        }
        session.setMetadata(mb.build());

        long acts = PlaybackState.ACTION_PLAY | PlaybackState.ACTION_PAUSE | PlaybackState.ACTION_PLAY_PAUSE
            | PlaybackState.ACTION_SKIP_TO_NEXT | PlaybackState.ACTION_SKIP_TO_PREVIOUS;
        if (durMs > 0) {
            acts |= PlaybackState.ACTION_SEEK_TO;
        }
        session.setPlaybackState(new PlaybackState.Builder()
            .setActions(acts)
            .setState(playing ? PlaybackState.STATE_PLAYING : PlaybackState.STATE_PAUSED,
                durMs > 0 ? posMs : PlaybackState.PLAYBACK_POSITION_UNKNOWN, 1f)
            .build());

        Notification n = buildNotification();
        if (Build.VERSION.SDK_INT >= 29) {
            startForeground(1, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PLAYBACK);
        } else {
            startForeground(1, n);
        }

        handler.removeCallbacks(idleStop);
        if (playing) {
            acquireLock();
        } else {
            releaseLock();
            handler.postDelayed(idleStop, 10 * 60 * 1000L);
        }
    }

    private Notification buildNotification() {
        Notification.Builder b;
        if (Build.VERSION.SDK_INT >= 26) {
            NotificationManager nm = (NotificationManager) getSystemService(NOTIFICATION_SERVICE);
            nm.createNotificationChannel(new NotificationChannel("lecteur", "Lecture", NotificationManager.IMPORTANCE_LOW));
            b = new Notification.Builder(this, "lecteur");
        } else {
            b = new Notification.Builder(this);
        }
        b.setSmallIcon(android.R.drawable.ic_media_play)
            .setContentTitle(title)
            .setContentText(channel)
            .setOngoing(playing)
            .setVisibility(Notification.VISIBILITY_PUBLIC)
            .addAction(act(android.R.drawable.ic_media_previous, "Précédente", "prev"))
            .addAction(act(playing ? android.R.drawable.ic_media_pause : android.R.drawable.ic_media_play, playing ? "Pause" : "Lecture", "toggle"))
            .addAction(act(android.R.drawable.ic_media_next, "Suivante", "next"))
            .setStyle(new Notification.MediaStyle()
                .setMediaSession(session.getSessionToken())
                .setShowActionsInCompactView(0, 1, 2));
        if (art != null) {
            b.setLargeIcon(art);
        }
        Intent open = new Intent(this, MainActivity.class);
        open.setFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP | Intent.FLAG_ACTIVITY_NEW_TASK);
        b.setContentIntent(PendingIntent.getActivity(this, 0, open, PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT));
        return b.build();
    }

    private Notification.Action act(int icon, String label, String action) {
        Intent i = new Intent(this, KeepAliveService.class);
        i.setAction(action);
        PendingIntent pi = PendingIntent.getService(this, action.hashCode(), i, PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT);
        return new Notification.Action.Builder(Icon.createWithResource(this, icon), label, pi).build();
    }

    private void acquireLock() {
        if (lock == null) {
            PowerManager pm = (PowerManager) getSystemService(POWER_SERVICE);
            lock = pm.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "lecteur:play");
        }
        if (!lock.isHeld()) {
            lock.acquire(6 * 60 * 60 * 1000L);
        }
    }

    private void releaseLock() {
        if (lock != null && lock.isHeld()) {
            lock.release();
        }
    }

    @Override
    public void onDestroy() {
        handler.removeCallbacks(idleStop);
        releaseLock();
        if (session != null) {
            session.setActive(false);
            session.release();
        }
        inst = null;
        super.onDestroy();
    }

    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }
}
""" % PKG)

# 3. MainActivity : interface NativeBg appelée par la page
open(APP + "/MainActivity.java", "w", encoding="utf-8").write("""package %s;

import android.content.Intent;
import android.content.pm.PackageManager;
import android.os.Build;
import android.os.Bundle;
import android.webkit.JavascriptInterface;
import android.widget.Toast;
import com.getcapacitor.BridgeActivity;

public class MainActivity extends BridgeActivity {

    private void toast(final String m) {
        runOnUiThread(new Runnable() {
            @Override
            public void run() {
                Toast.makeText(MainActivity.this, m, Toast.LENGTH_SHORT).show();
            }
        });
    }

    @Override
    public void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        try {
            if (Build.VERSION.SDK_INT >= 33
                && checkSelfPermission("android.permission.POST_NOTIFICATIONS") != PackageManager.PERMISSION_GRANTED) {
                requestPermissions(new String[] {"android.permission.POST_NOTIFICATIONS"}, 4242);
            }
        } catch (Exception e) {
            // facultatif
        }
        if (getBridge() != null && getBridge().getWebView() != null) {
            KeepAliveService.web = getBridge().getWebView();
            getBridge().getWebView().addJavascriptInterface(new Object() {
                @JavascriptInterface
                public void meta(String title, String channel, String artUrl) {
                    KeepAliveService.setMeta(title, channel, artUrl);
                }

                @JavascriptInterface
                public void state(boolean playing, double pos, double dur) {
                    KeepAliveService.playing = playing;
                    KeepAliveService.posMs = (long) (pos * 1000);
                    KeepAliveService.durMs = (long) (dur * 1000);
                    if (playing) {
                        ensureService();
                    }
                    KeepAliveService s = KeepAliveService.inst;
                    if (s != null) {
                        s.refreshOnMain();
                    }
                }
            }, "NativeBg");
        }
    }

    private void ensureService() {
        if (KeepAliveService.inst != null) {
            return;
        }
        try {
            Intent i = new Intent(this, KeepAliveService.class);
            if (Build.VERSION.SDK_INT >= 26) {
                startForegroundService(i);
            } else {
                startService(i);
            }
        } catch (Exception e) {
            toast("Lecteur : démarrage refusé : " + e);
        }
    }

    @Override
    public void onDestroy() {
        try {
            stopService(new Intent(this, KeepAliveService.class));
        } catch (Exception e) {
            // ignoré
        }
        KeepAliveService.web = null;
        super.onDestroy();
    }
}
""" % PKG)

# 4. Manifest : permissions + service
m = "android/app/src/main/AndroidManifest.xml"
s = open(m, encoding="utf-8").read()
if "KeepAliveService" not in s:
    if "usesCleartextTraffic" not in s:
        s = s.replace("<application", '<application android:usesCleartextTraffic="true"', 1)
    s = s.replace("</application>", '    <service android:name=".KeepAliveService" android:exported="false" android:foregroundServiceType="mediaPlayback" />\n    </application>', 1)
    perms = "".join('    <uses-permission android:name="android.permission.%s" />\n' % p for p in ("FOREGROUND_SERVICE", "FOREGROUND_SERVICE_MEDIA_PLAYBACK", "WAKE_LOCK", "POST_NOTIFICATIONS"))
    s = s.replace("</manifest>", perms + "</manifest>", 1)
    open(m, "w", encoding="utf-8").write(s)
# 5. Flux http autorisés (contenu mixte) dans l'APK
c = json.load(open(CFG, encoding="utf-8"))
c.setdefault("android", {})["allowMixedContent"] = True
json.dump(c, open(CFG, "w", encoding="utf-8"), indent=2)
print("patch OK")
