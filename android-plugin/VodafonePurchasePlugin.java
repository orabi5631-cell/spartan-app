package com.spartan.cards;

import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;
import org.json.JSONArray;
import org.json.JSONObject;
import java.io.BufferedReader;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.zip.GZIPInputStream;

@CapacitorPlugin(name = "VodafonePurchase")
public class VodafonePurchasePlugin extends Plugin {

    private Map<String, String> commonHeaders() {
        Map<String, String> h = new LinkedHashMap<>();
        h.put("User-Agent", "okhttp/4.12.0");
        h.put("Accept-Encoding", "gzip");
        h.put("x-agent-operatingsystem", "16");
        h.put("clientId", "AnaVodafoneAndroid");
        h.put("Accept-Language", "ar");
        h.put("x-agent-device", "Samsung SM-A165F");
        h.put("x-agent-version", "2025.11.1");
        h.put("x-agent-build", "1063");
        h.put("digitalId", "");
        h.put("device-id", "b26ba335813fad21");
        return h;
    }

    private boolean isGzip(HttpURLConnection conn) {
        String enc = conn.getContentEncoding();
        return enc != null && enc.toLowerCase().contains("gzip");
    }

    private String readStream(InputStream is, boolean gzip) throws Exception {
        InputStream actual = gzip ? new GZIPInputStream(is) : is;
        BufferedReader r = new BufferedReader(new InputStreamReader(actual, "UTF-8"));
        StringBuilder sb = new StringBuilder();
        String line;
        while ((line = r.readLine()) != null) sb.append(line).append("\n");
        return sb.toString();
    }

    // ---------------- isVpnActive() : يتأكد إن مفيش VPN شغال ----------------
    @PluginMethod
    public void isVpnActive(PluginCall call) {
        boolean vpnActive = false;
        try {
            android.net.ConnectivityManager cm = (android.net.ConnectivityManager)
                    getContext().getSystemService(android.content.Context.CONNECTIVITY_SERVICE);
            android.net.Network network = cm.getActiveNetwork();
            if (network != null) {
                android.net.NetworkCapabilities capabilities = cm.getNetworkCapabilities(network);
                if (capabilities != null) {
                    vpnActive = capabilities.hasTransport(android.net.NetworkCapabilities.TRANSPORT_VPN);
                }
            }
        } catch (Exception ignore) {}
        JSObject result = new JSObject();
        result.put("active", vpnActive);
        call.resolve(result);
    }

    // ---------------- login() : يجيب رقم المرسل + اسم أول (لو موجود جوه التوكن) ----------------
    @PluginMethod
    public void login(final PluginCall call) {
        new Thread(new Runnable() {
            @Override
            public void run() {
                try {
                    String[] seamless = getSeamlessAndMsisdn();
                    JSObject result = new JSObject();
                    result.put("msisdn", seamless[1]);
                    result.put("firstName", decodeFirstNameFromJwt(seamless[0]));
                    call.resolve(result);
                } catch (Exception e) {
                    call.reject(e.getMessage() != null ? e.getMessage() : "Unknown error");
                }
            }
        }).start();
    }

    // بيحاول يفك تشفير جزء البيانات (payload) بتاع الـ seamlessToken لو هو JWT، ويدور على اسم جواه
    private String decodeFirstNameFromJwt(String token) {
        try {
            String[] parts = token.split("\\.");
            if (parts.length < 2) return null;
            String payloadB64 = parts[1];
            byte[] decoded = android.util.Base64.decode(payloadB64, android.util.Base64.URL_SAFE | android.util.Base64.NO_WRAP | android.util.Base64.NO_PADDING);
            JSONObject claims = new JSONObject(new String(decoded, "UTF-8"));
            String[] possibleKeys = {"given_name", "first_name", "firstName", "name", "full_name", "fullName", "displayName", "subscriberName", "customerName"};
            for (String key : possibleKeys) {
                if (claims.has(key)) {
                    String value = claims.optString(key, "").trim();
                    if (!value.isEmpty()) {
                        return value.split("\\s+")[0];
                    }
                }
            }
        } catch (Exception ignore) {
            // مش JWT أو مفيهوش اسم — هيتم التعامل معاها من جانب التطبيق
        }
        return null;
    }

    // ---------------- purchase() : نفس السكريبت بالظبط + رد خام كامل ----------------
    @PluginMethod
    public void purchase(final PluginCall call) {
        final String productId = call.getString("productId");
        final String receiver = call.getString("receiver");
        final String pin = call.getString("pin");
        if (productId == null) { call.reject("productId missing"); return; }
        if (receiver == null) { call.reject("receiver missing"); return; }
        if (pin == null) { call.reject("pin missing"); return; }

        new Thread(new Runnable() {
            @Override
            public void run() {
                StringBuilder log = new StringBuilder();
                try {
                    log.append("🔄 جاري تسجيل الدخول...\n");
                    String[] seamless = getSeamlessAndMsisdn();
                    String seamlessToken = seamless[0];
                    String msisdn = seamless[1];
                    log.append("✅ الرقم المرسل  ").append(msisdn).append("\n");

                    String accessToken = getAccessToken(seamlessToken);
                    log.append("✅ تم الحصول على التوكن\n");

                    log.append("🔄 تحديث التوكن...\n");
                    accessToken = getAccessToken(seamlessToken);

                    log.append("🔄 جاري تنفيذ عملية الشراء...\n");
                    Object[] order = placeOrder(productId, receiver, pin, msisdn, accessToken);
                    int status = (Integer) order[0];
                    String rawText = (String) order[1];

                    log.append("\n📦 الرد:\n").append(rawText).append("\n");

                    if (status == 200) {
                        try {
                            JSONObject j = new JSONObject(rawText);
                            if (j.has("code") && !j.optString("code").equals("0000")) {
                                log.append("⚠️ العملية فشلت بسبب: ").append(j.optString("reason", "خطأ غير معروف")).append("\n");
                            } else {
                                log.append("✅ تم إرسال الطلب بنجاح (تحقق من رصيدك)\n");
                            }
                        } catch (Exception ignore) {
                            log.append("✅ تم الاستلام\n");
                        }
                    } else {
                        log.append("❌ فشل الاتصال\n");
                    }

                    JSObject result = new JSObject();
                    result.put("status", status);
                    result.put("msisdn", msisdn);
                    result.put("raw", log.toString());
                    call.resolve(result);
                } catch (Exception e) {
                    log.append("\n❌ خطأ: ").append(e.getMessage() != null ? e.getMessage() : "غير معروف").append("\n");
                    JSObject result = new JSObject();
                    result.put("status", 0);
                    result.put("raw", log.toString());
                    call.resolve(result);
                }
            }
        }).start();
    }

    // ---------------- rechargeBalance() : شحن رصيد عادي (PaymentRecharge) ----------------
    @PluginMethod
    public void rechargeBalance(final PluginCall call) {
        final String receiver = call.getString("receiver");
        final String pin = call.getString("pin");
        final String amount = call.getString("amount");
        if (receiver == null) { call.reject("receiver missing"); return; }
        if (pin == null) { call.reject("pin missing"); return; }
        if (amount == null) { call.reject("amount missing"); return; }

        new Thread(new Runnable() {
            @Override
            public void run() {
                StringBuilder log = new StringBuilder();
                try {
                    log.append("🔄 جاري تسجيل الدخول...\n");
                    String[] seamless = getSeamlessAndMsisdn();
                    String seamlessToken = seamless[0];
                    String msisdn = seamless[1];
                    log.append("✅ الرقم المرسل  ").append(msisdn).append("\n");

                    String accessToken = getAccessToken(seamlessToken);
                    log.append("✅ تم الحصول على التوكن\n");

                    log.append("🔄 جاري تنفيذ عملية الشحن...\n");
                    Object[] order = placeRechargeOrder(receiver, pin, amount, msisdn, accessToken);
                    int status = (Integer) order[0];
                    String rawText = (String) order[1];

                    log.append("\n📦 الرد:\n").append(rawText).append("\n");

                    JSObject result = new JSObject();
                    result.put("status", status);
                    result.put("msisdn", msisdn);
                    result.put("raw", log.toString());
                    call.resolve(result);
                } catch (Exception e) {
                    log.append("\n❌ خطأ: ").append(e.getMessage() != null ? e.getMessage() : "غير معروف").append("\n");
                    JSObject result = new JSObject();
                    result.put("status", 0);
                    result.put("raw", log.toString());
                    call.resolve(result);
                }
            }
        }).start();
    }

    private String[] getSeamlessAndMsisdn() throws Exception {
        URL url = new URL("http://mobile.vodafone.com.eg/checkSeamless/realms/vf-realm/protocol/openid-connect/auth?client_id=cash-app");
        HttpURLConnection conn = (HttpURLConnection) url.openConnection();
        conn.setRequestMethod("GET");
        for (Map.Entry<String, String> e : commonHeaders().entrySet()) conn.setRequestProperty(e.getKey(), e.getValue());
        conn.setRequestProperty("Connection", "Keep-Alive");

        if (conn.getResponseCode() != 200) throw new Exception("فشل seamlessToken (" + conn.getResponseCode() + ")");
        JSONObject data = new JSONObject(readStream(conn.getInputStream(), isGzip(conn)));
        String rawMsisdn = data.optString("msisdn");
        String formatted = rawMsisdn.startsWith("1") ? "0" + rawMsisdn : rawMsisdn;
        return new String[]{ data.optString("seamlessToken"), formatted };
    }

    private String getAccessToken(String seamlessToken) throws Exception {
        URL url = new URL("https://mobile.vodafone.com.eg/auth/realms/vf-realm/protocol/openid-connect/token");
        HttpURLConnection conn = (HttpURLConnection) url.openConnection();
        conn.setRequestMethod("POST");
        conn.setDoOutput(true);
        for (Map.Entry<String, String> e : commonHeaders().entrySet()) conn.setRequestProperty(e.getKey(), e.getValue());
        conn.setRequestProperty("Accept", "application/json, text/plain, */*");
        conn.setRequestProperty("silentLogin", "true");
        conn.setRequestProperty("CRP", "false");
        conn.setRequestProperty("seamlessToken", seamlessToken);
        conn.setRequestProperty("firstTimeLogin", "true");
        conn.setRequestProperty("Content-Type", "application/x-www-form-urlencoded");

        String body = "grant_type=password&client_secret=b86e30a8-ae29-467a-a71f-65c73f2ff5e3&client_id=cash-app";
        OutputStream os = conn.getOutputStream();
        os.write(body.getBytes("UTF-8"));
        os.flush();
        os.close();

        if (conn.getResponseCode() != 200) throw new Exception("فشل access_token (" + conn.getResponseCode() + ")");
        JSONObject data = new JSONObject(readStream(conn.getInputStream(), isGzip(conn)));
        return data.optString("access_token");
    }

    private Object[] placeOrder(String productId, String receiver, String pin, String msisdnSender, String accessToken) throws Exception {
        URL url = new URL("https://mobile.vodafone.com.eg/services/dxl/pom/productOrder");
        HttpURLConnection conn = (HttpURLConnection) url.openConnection();
        conn.setRequestMethod("POST");
        conn.setDoOutput(true);
        for (Map.Entry<String, String> e : commonHeaders().entrySet()) conn.setRequestProperty(e.getKey(), e.getValue());
        conn.setRequestProperty("Accept", "application/json");
        conn.setRequestProperty("api-host", "ProductOrderingManagement");
        conn.setRequestProperty("useCase", "CashFakkaAndMared");
        conn.setRequestProperty("api-version", "v2");
        conn.setRequestProperty("msisdn", msisdnSender);
        conn.setRequestProperty("Authorization", "Bearer " + accessToken);
        conn.setRequestProperty("Content-Type", "application/json; charset=UTF-8");

        JSONObject characteristic1 = new JSONObject().put("name", "PaymentMethod").put("value", "VFCash");
        JSONObject characteristic2 = new JSONObject().put("name", "USE_EMONEY").put("value", "False");
        JSONObject characteristic3 = new JSONObject().put("name", "MerchantCode").put("value", "81841829");
        JSONArray characteristics = new JSONArray().put(characteristic1).put(characteristic2).put(characteristic3);

        JSONObject partySender = new JSONObject().put("id", msisdnSender).put("name", "MSISDN").put("role", "Subscriber");
        JSONObject partyReceiver = new JSONObject().put("id", receiver).put("name", "Receiver").put("role", "Receiver");
        JSONArray relatedParties = new JSONArray().put(partySender).put(partyReceiver);

        JSONObject product = new JSONObject().put("id", productId).put("characteristic", characteristics).put("relatedParty", relatedParties);

        JSONObject orderItem = new JSONObject()
                .put("action", "insert")
                .put("id", productId)
                .put("@type", productId)
                .put("eCode", 0)
                .put("product", product);

        JSONObject pinParty = new JSONObject().put("id", pin).put("name", "pin").put("role", "Requestor");

        JSONObject payload = new JSONObject()
                .put("channel", new JSONObject().put("name", "MobileApp"))
                .put("orderItem", new JSONArray().put(orderItem))
                .put("relatedParty", new JSONArray().put(pinParty))
                .put("@type", "CashFakkaAndMared");

        OutputStream os = conn.getOutputStream();
        os.write(payload.toString().getBytes("UTF-8"));
        os.flush();
        os.close();

        int status = conn.getResponseCode();
        InputStream stream = (status >= 200 && status < 300) ? conn.getInputStream() : conn.getErrorStream();
        String text = readStream(stream, isGzip(conn));
        return new Object[]{ status, text };
    }

    private Object[] placeRechargeOrder(String receiver, String pin, String amount, String msisdnSender, String accessToken) throws Exception {
        URL url = new URL("https://mobile.vodafone.com.eg/services/dxl/orderor/productOrder");
        HttpURLConnection conn = (HttpURLConnection) url.openConnection();
        conn.setRequestMethod("POST");
        conn.setDoOutput(true);
        for (Map.Entry<String, String> e : commonHeaders().entrySet()) conn.setRequestProperty(e.getKey(), e.getValue());
        conn.setRequestProperty("Accept", "application/json");
        conn.setRequestProperty("Content-Type", "application/json; charset=UTF-8");
        conn.setRequestProperty("api-version", "v2");
        conn.setRequestProperty("msisdn", msisdnSender);
        conn.setRequestProperty("X-Request-ID", java.util.UUID.randomUUID().toString());
        conn.setRequestProperty("Authorization", "Bearer " + accessToken);

        JSONObject paymentChar1 = new JSONObject().put("name", "authorizationCode").put("value", pin);
        JSONObject paymentChar2 = new JSONObject().put("name", "digitalTransactionId").put("value", java.util.UUID.randomUUID().toString().replace("-", "").substring(0, 13));
        JSONObject payment = new JSONObject()
                .put("characteristics", new JSONArray().put(paymentChar1).put(paymentChar2))
                .put("@type", "digitalWallet");

        JSONObject itemChar1 = new JSONObject().put("name", "MSISDN").put("@type", "receiver").put("value", receiver);
        JSONObject itemChar2 = new JSONObject().put("name", "MSISDN").put("@type", "sender").put("value", msisdnSender);
        JSONObject taxIncluded = new JSONObject().put("unit", "EGP").put("value", Double.parseDouble(amount));
        JSONObject price = new JSONObject().put("taxIncludedAmount", taxIncluded);
        JSONObject itemTotalPrice = new JSONObject().put("price", price);
        JSONObject productOrderItem = new JSONObject()
                .put("characteristics", new JSONArray().put(itemChar1).put(itemChar2))
                .put("itemTotalPrice", new JSONArray().put(itemTotalPrice));

        JSONObject payload = new JSONObject()
                .put("payment", new JSONArray().put(payment))
                .put("productOrderItem", new JSONArray().put(productOrderItem))
                .put("@type", "paymentRecharge");

        OutputStream os = conn.getOutputStream();
        os.write(payload.toString().getBytes("UTF-8"));
        os.flush();
        os.close();

        int status = conn.getResponseCode();
        InputStream stream = (status >= 200 && status < 300) ? conn.getInputStream() : conn.getErrorStream();
        String text = readStream(stream, isGzip(conn));
        return new Object[]{ status, text };
    }
}
