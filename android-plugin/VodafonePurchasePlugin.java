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

    private String readStream(InputStream is) throws Exception {
        BufferedReader r = new BufferedReader(new InputStreamReader(is, "UTF-8"));
        StringBuilder sb = new StringBuilder();
        String line;
        while ((line = r.readLine()) != null) sb.append(line);
        return sb.toString();
    }

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
                try {
                    String[] seamless = getSeamlessAndMsisdn();
                    String seamlessToken = seamless[0];
                    String msisdn = seamless[1];
                    String accessToken = getAccessToken(seamlessToken);
                    Object[] order = placeOrder(productId, receiver, pin, msisdn, accessToken);

                    JSObject result = new JSObject();
                    result.put("status", (Integer) order[0]);
                    result.put("msisdn", msisdn);
                    result.put("raw", (String) order[1]);
                    call.resolve(result);
                } catch (Exception e) {
                    call.reject(e.getMessage() != null ? e.getMessage() : "Unknown error");
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
        JSONObject data = new JSONObject(readStream(conn.getInputStream()));
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
        JSONObject data = new JSONObject(readStream(conn.getInputStream()));
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
        String text = readStream(stream);
        return new Object[]{ status, text };
    }
          }
