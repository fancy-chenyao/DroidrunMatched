package Agent

import android.content.Context
import android.graphics.Bitmap
import android.util.Log
import okhttp3.MediaType.Companion.toMediaTypeOrNull
import okhttp3.MultipartBody
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody
import okhttp3.RequestBody.Companion.asRequestBody
import org.json.JSONObject
import java.io.ByteArrayOutputStream
import java.io.File
import java.io.FileOutputStream
import java.util.concurrent.TimeUnit

object HttpUploader {
    
    private const val TAG = "HttpUploader"
    
    private val client: OkHttpClient by lazy {
        OkHttpClient.Builder()
            .connectTimeout(10, TimeUnit.SECONDS)
            .readTimeout(60, TimeUnit.SECONDS)
            .writeTimeout(60, TimeUnit.SECONDS)
            .callTimeout(75, TimeUnit.SECONDS)
            .retryOnConnectionFailure(true)
            .build()
    }
    
    private fun getDeviceId(ctx: Context): String {
        val sp = ctx.getSharedPreferences("mobilegpt_prefs", Context.MODE_PRIVATE)
        var id = sp.getString(MobileGPTGlobal.DEVICE_ID_KEY, null)
        if (id.isNullOrEmpty()) {
            id = java.util.UUID.randomUUID().toString()
            sp.edit().putString(MobileGPTGlobal.DEVICE_ID_KEY, id).apply()
        }
        return id
    }
    
    private fun bitmapToJpegFile(context: Context, bitmap: Bitmap, quality: Int = 80): File {
        val cacheDir = File(context.cacheDir, "uploads")
        if (!cacheDir.exists()) cacheDir.mkdirs()
        val file = File.createTempFile("screenshot_", ".jpg", cacheDir)
        val bos = ByteArrayOutputStream()
        bitmap.compress(Bitmap.CompressFormat.JPEG, quality, bos)
        val bytes = bos.toByteArray()
        FileOutputStream(file).use { it.write(bytes) }
        return file
    }
    
    fun uploadBitmap(context: Context, bitmap: Bitmap, requestId: String): JSONObject? {
        val deviceId = getDeviceId(context)
        val url = MobileGPTGlobal.uploadBaseUrl()
        val t0 = System.currentTimeMillis()
        return try {
            val file = bitmapToJpegFile(context, bitmap, 80)
            val body: RequestBody = MultipartBody.Builder()
                .setType(MultipartBody.FORM)
                .addFormDataPart("device_id", deviceId)
                .addFormDataPart("request_id", requestId)
                .addFormDataPart(
                    "file",
                    file.name,
                    file.asRequestBody("image/jpeg".toMediaTypeOrNull())
                )
                .build()
            val request = Request.Builder()
                .url(url)
                .post(body)
                .build()
            client.newCall(request).execute().use { resp ->
                val ms = System.currentTimeMillis() - t0
                if (!resp.isSuccessful) {
                    Log.e(TAG, "上传失败: code=${resp.code}, time=${ms}ms")
                    return null
                }
                val respStr = resp.body?.string() ?: ""
                Log.d(TAG, "上传成功: ${respStr.take(256)}, time=${ms}ms")
                return JSONObject(respStr)
            }
        } catch (e: Exception) {
            Log.e(TAG, "上传异常", e)
            null
        }
    }
    
    fun uploadJson(context: Context, json: String, requestId: String, filenameHint: String = "a11y.json"): JSONObject? {
        val deviceId = getDeviceId(context)
        val url = MobileGPTGlobal.uploadBaseUrl()
        val t0 = System.currentTimeMillis()
        return try {
            val cacheDir = File(context.cacheDir, "uploads")
            if (!cacheDir.exists()) cacheDir.mkdirs()
            val file = File.createTempFile(filenameHint.substringBefore("."), ".json", cacheDir)
            file.writeText(json, Charsets.UTF_8)
            val body: RequestBody = MultipartBody.Builder()
                .setType(MultipartBody.FORM)
                .addFormDataPart("device_id", deviceId)
                .addFormDataPart("request_id", requestId)
                .addFormDataPart(
                    "file",
                    file.name,
                    file.asRequestBody("application/json".toMediaTypeOrNull())
                )
                .build()
            val request = Request.Builder()
                .url(url)
                .post(body)
                .build()
            client.newCall(request).execute().use { resp ->
                val ms = System.currentTimeMillis() - t0
                if (!resp.isSuccessful) {
                    Log.e(TAG, "上传JSON失败: code=${resp.code}, time=${ms}ms")
                    return null
                }
                val respStr = resp.body?.string() ?: ""
                Log.d(TAG, "上传JSON成功: ${respStr.take(256)}, time=${ms}ms")
                return JSONObject(respStr)
            }
        } catch (e: Exception) {
            Log.e(TAG, "上传JSON异常", e)
            null
        }
    }
}


