package com.spartan.cards

import com.getcapacitor.JSObject
import com.getcapacitor.Plugin
import com.getcapacitor.PluginCall
import com.getcapacitor.PluginMethod
import com.getcapacitor.annotation.CapacitorPlugin
import org.json.JSONObject
import java.io.OutputStream
import java.net.HttpURLConnection
import java.net.URL

@CapacitorPlugin(name = "VodafonePurchase")
class VodafonePurchasePlugin : Plugin() {

    private val commonHeaders = mapOf(
        "User-Agent" to "okhttp/4.12.0",
        "Accept-Encoding" to "gzip",
        "x-agent-operatingsystem" to "16",
        "clientId" to "AnaVodafoneAndroid",
        "Accept-Language" to "ar",
        "x-agent-device" to "Samsung SM-A165F",
        "x-agent-version" to "2025.11.1",
        "x-agent-build" to "1063",
        "digitalId" to "",
        "device-id" to "b26ba335813fad21"
    )

    @PluginMethod
    fun purchase(call: PluginCall) {
        val productId = call.getString("productId") ?: return call.reject("productId missing")
        val receiver = call.getString("receiver") ?: return call.reject("receiver missing")
        val pin = call.getString("pin") ?: return call.reject("pin missing")

        Thread {
            try {
                val (seamlessToken, msisdn) = getSeamlessAndMsisdn()
                val accessToken = getAccessToken(seamlessToken)
                val (status, body) = placeOrder(productId, receiver, pin, msisdn, accessToken)

                val result = JSObject()
                result.put("status", status)
                result.put("msisdn", msisdn)
                result.put("raw", body)
                call.resolve(result)
            } catch (e: Exception) {
                call.reject(e.message ?: "Unknown error")
            }
        }.start()
    }

    private fun getSeamlessAndMsisdn(): Pair<String, String> {
        val url = URL("http://mobile.vodafone.com.eg/checkSeamless/realms/vf-realm/protocol/openid-connect/auth?client_id=cash-app")
        val conn = url.openConnection() as HttpURLConnection
        conn.requestMethod = "GET"
        commonHeaders.forEach { (k, v) -> conn.setRequestProperty(k, v) }
        conn.setRequestProperty("Connection", "Keep-Alive")

        if (conn.responseCode != 200) throw Exception("فشل seamlessToken (${conn.responseCode})")
        val data = JSONObject(conn.inputStream.bufferedReader().readText())
        val rawMsisdn = data.optString("msisdn")
        val formatted = if (rawMsisdn.startsWith("1")) "0$rawMsisdn" else rawMsisdn
        return Pair(data.optString("seamlessToken"), formatted)
    }

    private fun getAccessToken(seamlessToken: String): String {
        val url = URL("https://mobile.vodafone.com.eg/auth/realms/vf-realm/protocol/openid-connect/token")
        val conn = url.openConnection() as HttpURLConnection
        conn.requestMethod = "POST"
        conn.doOutput = true
        commonHeaders.forEach { (k, v) -> conn.setRequestProperty(k, v) }
        conn.setRequestProperty("Accept", "application/json, text/plain, */*")
        conn.setRequestProperty("silentLogin", "true")
        conn.setRequestProperty("CRP", "false")
        conn.setRequestProperty("seamlessToken", seamlessToken)
        conn.setRequestProperty("firstTimeLogin", "true")
        conn.setRequestProperty("Content-Type", "application/x-www-form-urlencoded")

        val body = "grant_type=password&client_secret=b86e30a8-ae29-467a-a71f-65c73f2ff5e3&client_id=cash-app"
        val os: OutputStream = conn.outputStream
        os.write(body.toByteArray())
        os.flush()
        os.close()

        if (conn.responseCode != 200) throw Exception("فشل access_token (${conn.responseCode})")
        val data = JSONObject(conn.inputStream.bufferedReader().readText())
        return data.optString("access_token")
    }

    private fun placeOrder(
        productId: String, receiver: String, pin: String,
        msisdnSender: String, accessToken: String
    ): Pair<Int, String> {
        val url = URL("https://mobile.vodafone.com.eg/services/dxl/pom/productOrder")
        val conn = url.openConnection() as HttpURLConnection
        conn.requestMethod = "POST"
        conn.doOutput = true
        commonHeaders.forEach { (k, v) -> conn.setRequestProperty(k, v) }
        conn.setRequestProperty("Accept", "application/json")
        conn.setRequestProperty("api-host", "ProductOrderingManagement")
        conn.setRequestProperty("useCase", "CashFakkaAndMared")
        conn.setRequestProperty("api-version", "v2")
        conn.setRequestProperty("msisdn", msisdnSender)
        conn.setRequestProperty("Authorization", "Bearer $accessToken")
        conn.setRequestProperty("Content-Type", "application/json; charset=UTF-8")

        val payload = JSONObject().apply {
            put("channel", JSONObject().put("name", "MobileApp"))
            put("orderItem", org.json.JSONArray().put(JSONObject().apply {
                put("action", "insert")
                put("id", productId)
                put("@type", productId)
                put("eCode", 0)
                put("product", JSONObject().apply {
                    put("id", productId)
                    put("characteristic", org.json.JSONArray()
                        .put(JSONObject().put("name", "PaymentMethod").put("value", "VFCash"))
                        .put(JSONObject().put("name", "USE_EMONEY").put("value", "False"))
                        .put(JSONObject().put("name", "MerchantCode").put("value", "81841829")))
                    put("relatedParty", org.json.JSONArray()
                        .put(JSONObject().put("id", msisdnSender).put("name", "MSISDN").put("role", "Subscriber"))
                        .put(JSONObject().put("id", receiver).put("name", "Receiver").put("role", "Receiver")))
                })
            }))
            put("relatedParty", org.json.JSONArray().put(JSONObject().put("id", pin).put("name", "pin").put("role", "Requestor")))
            put("@type", "CashFakkaAndMared")
        }

        val os: OutputStream = conn.outputStream
        os.write(payload.toString().toByteArray())
        os.flush()
        os.close()

        val status = conn.responseCode
        val stream = if (status in 200..299) conn.inputStream else conn.errorStream
        val text = stream.bufferedReader().readText()
        return Pair(status, text)
    }
}
