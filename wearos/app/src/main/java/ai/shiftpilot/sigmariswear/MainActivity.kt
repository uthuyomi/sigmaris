package ai.shiftpilot.sigmariswear

import android.Manifest
import android.app.Activity
import android.content.ActivityNotFoundException
import android.content.Context
import android.content.Intent
import android.content.SharedPreferences
import android.content.pm.PackageManager
import android.os.Bundle
import android.speech.RecognizerIntent
import android.speech.tts.TextToSpeech
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.Mic
import androidx.compose.material.icons.rounded.VolumeUp
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.wear.compose.material.Button
import androidx.wear.compose.material.ButtonDefaults
import androidx.wear.compose.material.Chip
import androidx.wear.compose.material.ChipDefaults
import androidx.wear.compose.material.Icon
import androidx.wear.compose.material.MaterialTheme
import androidx.wear.compose.material.PositionIndicator
import androidx.wear.compose.material.Scaffold
import androidx.wear.compose.material.ScalingLazyColumn
import androidx.wear.compose.material.Text
import androidx.wear.compose.material.rememberScalingLazyListState
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONArray
import org.json.JSONObject
import java.io.IOException
import java.util.Locale
import java.util.concurrent.TimeUnit

class MainActivity : ComponentActivity(), TextToSpeech.OnInitListener {
    private lateinit var prefs: SharedPreferences
    private lateinit var tts: TextToSpeech
    private var speechResultHandler: (String) -> Unit = {}
    private var speechErrorHandler: (String) -> Unit = {}

    private val speechLauncher =
        registerForActivityResult(ActivityResultContracts.StartActivityForResult()) { result ->
            if (result.resultCode != Activity.RESULT_OK) return@registerForActivityResult
            val text = result.data
                ?.getStringArrayListExtra(RecognizerIntent.EXTRA_RESULTS)
                ?.firstOrNull()
                ?.trim()
                .orEmpty()
            if (text.isNotBlank()) speechResultHandler(text)
        }

    private val microphonePermissionLauncher =
        registerForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
            if (granted) {
                launchSpeechRecognizer()
            } else {
                speechErrorHandler("マイク権限が必要です。")
            }
        }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        prefs = getSharedPreferences("sigmaris_wear", Context.MODE_PRIVATE)
        tts = TextToSpeech(this, this)

        setContent {
            SigmarisWearApp(
                prefs = prefs,
                onStartVoiceInput = { onResult, onError ->
                    speechResultHandler = onResult
                    speechErrorHandler = onError
                    requestSpeechInput()
                },
                onSpeak = { text -> speak(text) },
            )
        }
    }

    override fun onInit(status: Int) {
        if (status == TextToSpeech.SUCCESS) {
            tts.language = Locale.JAPAN
        }
    }

    override fun onDestroy() {
        tts.stop()
        tts.shutdown()
        super.onDestroy()
    }

    private fun requestSpeechInput() {
        if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED) {
            launchSpeechRecognizer()
        } else {
            microphonePermissionLauncher.launch(Manifest.permission.RECORD_AUDIO)
        }
    }

    private fun launchSpeechRecognizer() {
        val intent = Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).apply {
            putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
            putExtra(RecognizerIntent.EXTRA_LANGUAGE, Locale.JAPAN.toLanguageTag())
            putExtra(RecognizerIntent.EXTRA_PROMPT, "シグマリスに話す")
        }
        try {
            speechLauncher.launch(intent)
        } catch (_: ActivityNotFoundException) {
            speechErrorHandler("この端末では音声入力を起動できません。")
        }
    }

    private fun speak(text: String) {
        if (text.isBlank()) return
        tts.speak(text, TextToSpeech.QUEUE_FLUSH, null, "sigmaris-reply")
    }
}

private const val KEY_BACKEND_URL = "backend_url"

private data class ChatMessage(
    val role: Role,
    val content: String,
)

private enum class Role {
    User,
    Assistant,
}

private data class SigmarisReply(
    val text: String,
    val threadId: String?,
)

private data class AuthTokens(
    val accessToken: String,
    val refreshToken: String,
    val expiresAtMillis: Long,
)

private class NotLoggedInException(message: String) : IOException(message)
private class UnauthorizedException(message: String) : IOException(message)

/** Talks directly to Supabase Auth to exchange email/password (or a refresh token) for a JWT. */
private class SupabaseAuthClient {
    private val httpClient = OkHttpClient.Builder()
        .connectTimeout(10, TimeUnit.SECONDS)
        .readTimeout(20, TimeUnit.SECONDS)
        .build()

    suspend fun signInWithPassword(email: String, password: String): AuthTokens =
        tokenRequest("password", JSONObject().put("email", email).put("password", password))

    suspend fun refresh(refreshToken: String): AuthTokens =
        tokenRequest("refresh_token", JSONObject().put("refresh_token", refreshToken))

    private suspend fun tokenRequest(grantType: String, body: JSONObject): AuthTokens =
        withContext(Dispatchers.IO) {
            val supabaseUrl = BuildConfig.SUPABASE_URL.trimEnd('/')
            require(supabaseUrl.isNotBlank() && BuildConfig.SUPABASE_KEY.isNotBlank()) {
                "SUPABASE_URL / SUPABASE_KEY が設定されていません（local.properties を確認）。"
            }

            val request = Request.Builder()
                .url("$supabaseUrl/auth/v1/token?grant_type=$grantType")
                .header("apikey", BuildConfig.SUPABASE_KEY)
                .header("Content-Type", "application/json")
                .post(body.toString().toRequestBody("application/json; charset=utf-8".toMediaType()))
                .build()

            httpClient.newCall(request).execute().use { response ->
                val responseText = response.body.string()
                val json = runCatching { JSONObject(responseText) }.getOrNull()
                if (!response.isSuccessful || json == null || !json.has("access_token")) {
                    val message = json?.optString("error_description")
                        ?.takeIf { it.isNotBlank() }
                        ?: json?.optString("msg")?.takeIf { it.isNotBlank() }
                        ?: "ログインに失敗しました（${response.code}）"
                    throw IOException(message)
                }
                AuthTokens(
                    accessToken = json.getString("access_token"),
                    refreshToken = json.getString("refresh_token"),
                    expiresAtMillis = System.currentTimeMillis() + json.optLong("expires_in", 3600L) * 1000,
                )
            }
        }
}

/** Owns the current session: persists the refresh token and silently renews the access token. */
private class AuthManager(private val prefs: SharedPreferences, private val authClient: SupabaseAuthClient) {
    private var accessToken: String? = null
    private var accessTokenExpiresAt: Long = 0L

    val storedEmail: String get() = prefs.getString(KEY_EMAIL, "").orEmpty()
    private val storedRefreshToken: String? get() = prefs.getString(KEY_REFRESH_TOKEN, null)
    val hasStoredSession: Boolean get() = !storedRefreshToken.isNullOrBlank()

    suspend fun loginWithPassword(email: String, password: String) {
        val tokens = authClient.signInWithPassword(email, password)
        applyTokens(tokens)
        prefs.edit().putString(KEY_EMAIL, email.trim()).apply()
    }

    /** Returns a usable access token, silently refreshing from the stored refresh token if needed. */
    suspend fun currentAccessToken(forceRefresh: Boolean = false): String {
        val cached = accessToken
        if (!forceRefresh && cached != null && System.currentTimeMillis() < accessTokenExpiresAt - REFRESH_SKEW_MS) {
            return cached
        }
        val refreshToken = storedRefreshToken
            ?: throw NotLoggedInException("ログインしてください。")
        val tokens = authClient.refresh(refreshToken)
        applyTokens(tokens)
        return tokens.accessToken
    }

    fun logout() {
        accessToken = null
        accessTokenExpiresAt = 0L
        prefs.edit().remove(KEY_REFRESH_TOKEN).apply()
    }

    private fun applyTokens(tokens: AuthTokens) {
        accessToken = tokens.accessToken
        accessTokenExpiresAt = tokens.expiresAtMillis
        prefs.edit().putString(KEY_REFRESH_TOKEN, tokens.refreshToken).apply()
    }

    companion object {
        private const val KEY_EMAIL = "auth_email"
        private const val KEY_REFRESH_TOKEN = "auth_refresh_token"
        private const val REFRESH_SKEW_MS = 30_000L
    }
}

private class SigmarisClient {
    private val httpClient = OkHttpClient.Builder()
        .connectTimeout(10, TimeUnit.SECONDS)
        .readTimeout(90, TimeUnit.SECONDS)
        .writeTimeout(20, TimeUnit.SECONDS)
        .build()

    suspend fun sendMessage(
        backendUrl: String,
        accessToken: String,
        threadId: String?,
        messages: List<ChatMessage>,
    ): SigmarisReply = withContext(Dispatchers.IO) {
        val baseUrl = backendUrl.trim().trimEnd('/')
        require(baseUrl.startsWith("http://") || baseUrl.startsWith("https://")) {
            "Backend URL は http:// または https:// で始めてください。"
        }

        val body = JSONObject()
            .put(
                "messages",
                JSONArray().apply {
                    messages.forEach { message ->
                        put(
                            JSONObject()
                                .put("role", if (message.role == Role.User) "user" else "assistant")
                                .put("content", message.content),
                        )
                    }
                },
            )
            .put("thread_id", threadId)
            .put(
                "context",
                JSONObject().put("reason", "User submitted a message from Wear OS."),
            )
            .toString()
            .toRequestBody("application/json; charset=utf-8".toMediaType())

        val request = Request.Builder()
            .url("$baseUrl/api/orchestrator/chat")
            .header("Authorization", "Bearer $accessToken")
            .header("Content-Type", "application/json")
            .post(body)
            .build()

        httpClient.newCall(request).execute().use { response ->
            val responseText = response.body.string()
            if (response.code == 401) {
                throw UnauthorizedException("認証の有効期限が切れました。")
            }
            if (!response.isSuccessful) {
                throw IOException("Sigmaris API ${response.code}: ${responseText.take(160)}")
            }
            val json = JSONObject(responseText)
            SigmarisReply(
                text = json.optString("text").trim(),
                threadId = json.optString("thread_id").takeIf { it.isNotBlank() },
            )
        }
    }

    suspend fun checkHealth(backendUrl: String): String = withContext(Dispatchers.IO) {
        val baseUrl = backendUrl.trim().trimEnd('/')
        require(baseUrl.startsWith("http://") || baseUrl.startsWith("https://")) {
            "Backend URL は http:// または https:// で始めてください。"
        }

        val request = Request.Builder()
            .url("$baseUrl/health")
            .get()
            .build()

        httpClient.newCall(request).execute().use { response ->
            val responseText = response.body.string()
            if (!response.isSuccessful) {
                throw IOException("Backend health ${response.code}: ${responseText.take(120)}")
            }
            val json = JSONObject(responseText)
            "backend: ${json.optString("status", "unknown")}"
        }
    }
}

private const val STATUS_COMMAND = "/status"
private const val STATUS_QUERY = "現在の認知状態（自己認識・目標・気分・進行中の思考）を簡潔に教えてください。"

@Composable
private fun SigmarisWearApp(
    prefs: SharedPreferences,
    onStartVoiceInput: ((String) -> Unit, (String) -> Unit) -> Unit,
    onSpeak: (String) -> Unit,
) {
    MaterialTheme {
        val scope = rememberCoroutineScope()
        val authClient = remember { SupabaseAuthClient() }
        val authManager = remember { AuthManager(prefs, authClient) }
        val client = remember { SigmarisClient() }

        var sessionChecked by rememberSaveable { mutableStateOf(false) }
        var loggedIn by rememberSaveable { mutableStateOf(false) }

        LaunchedEffect(Unit) {
            if (authManager.hasStoredSession) {
                loggedIn = runCatching { authManager.currentAccessToken() }.isSuccess
            }
            sessionChecked = true
        }

        when {
            !sessionChecked -> LoadingScreen()
            !loggedIn -> LoginScreen(
                initialEmail = authManager.storedEmail,
                onLogin = { email, password, onError ->
                    scope.launch {
                        try {
                            authManager.loginWithPassword(email, password)
                            loggedIn = true
                        } catch (exception: Exception) {
                            onError(exception.message ?: "ログインに失敗しました。")
                        }
                    }
                },
            )
            else -> ChatScreen(
                prefs = prefs,
                authManager = authManager,
                client = client,
                onLoggedOut = { loggedIn = false },
                onStartVoiceInput = onStartVoiceInput,
                onSpeak = onSpeak,
            )
        }
    }
}

@Composable
private fun LoadingScreen() {
    Box(
        modifier = Modifier
            .fillMaxSize()
            .background(Color(0xFF050505)),
        contentAlignment = Alignment.Center,
    ) {
        Text(text = "セッション確認中...", color = Color.White, fontSize = 12.sp)
    }
}

@Composable
private fun LoginScreen(
    initialEmail: String,
    onLogin: (String, String, (String) -> Unit) -> Unit,
) {
    var email by rememberSaveable { mutableStateOf(initialEmail) }
    var password by rememberSaveable { mutableStateOf("") }
    var error by rememberSaveable { mutableStateOf<String?>(null) }
    var isLoggingIn by rememberSaveable { mutableStateOf(false) }
    val listState = rememberScalingLazyListState()

    Scaffold(
        positionIndicator = { PositionIndicator(scalingLazyListState = listState) },
    ) {
        Box(
            modifier = Modifier
                .fillMaxSize()
                .background(Color(0xFF050505)),
        ) {
            ScalingLazyColumn(
                state = listState,
                modifier = Modifier.fillMaxSize(),
                contentPadding = PaddingValues(horizontal = 18.dp, vertical = 18.dp),
                horizontalAlignment = Alignment.CenterHorizontally,
                verticalArrangement = Arrangement.spacedBy(10.dp),
            ) {
                item {
                    Text(
                        text = "Sigmaris ログイン",
                        color = Color.White,
                        fontSize = 15.sp,
                        textAlign = TextAlign.Center,
                    )
                }
                item {
                    TinyInput(label = "メールアドレス", value = email, onValueChange = { email = it })
                }
                item {
                    TinyInput(label = "パスワード", value = password, onValueChange = { password = it }, isSecret = true)
                }
                item {
                    Button(
                        onClick = {
                            if (email.isBlank() || password.isBlank() || isLoggingIn) return@Button
                            isLoggingIn = true
                            error = null
                            onLogin(email, password) { message ->
                                error = message
                                isLoggingIn = false
                            }
                        },
                        enabled = !isLoggingIn,
                        colors = ButtonDefaults.buttonColors(
                            backgroundColor = Color(0xFF22C55E),
                            contentColor = Color.Black,
                        ),
                    ) {
                        Text(text = if (isLoggingIn) "ログイン中..." else "ログイン", fontSize = 12.sp)
                    }
                }
                if (error != null) {
                    item {
                        Bubble(text = error.orEmpty(), color = Color(0xFF4B1118), textColor = Color(0xFFFFCDD2))
                    }
                }
            }
        }
    }
}

@Composable
private fun ChatScreen(
    prefs: SharedPreferences,
    authManager: AuthManager,
    client: SigmarisClient,
    onLoggedOut: () -> Unit,
    onStartVoiceInput: ((String) -> Unit, (String) -> Unit) -> Unit,
    onSpeak: (String) -> Unit,
) {
    val scope = rememberCoroutineScope()
    val messages = remember { mutableStateListOf<ChatMessage>() }
    var backendUrl by rememberSaveable {
        mutableStateOf(prefs.getString(KEY_BACKEND_URL, BuildConfig.BACKEND_URL).orEmpty())
    }
    var threadId by rememberSaveable { mutableStateOf<String?>(null) }
    var status by rememberSaveable { mutableStateOf("待機中") }
    var error by rememberSaveable { mutableStateOf<String?>(null) }
    var isSending by rememberSaveable { mutableStateOf(false) }
    var connectionStatus by rememberSaveable { mutableStateOf("未確認") }
    val listState = rememberScalingLazyListState()

    fun saveBackendUrl(url: String) {
        backendUrl = url
        prefs.edit().putString(KEY_BACKEND_URL, url.trim()).apply()
    }

    fun checkBackend() {
        connectionStatus = "確認中"
        error = null
        scope.launch {
            try {
                connectionStatus = client.checkHealth(backendUrl)
            } catch (exception: Exception) {
                connectionStatus = "未接続"
                error = exception.message ?: "バックエンドに接続できません。"
            }
        }
    }

    fun submit(rawText: String) {
        val trimmed = rawText.trim()
        if (trimmed.isBlank() || isSending) return
        val outgoing = if (trimmed.equals(STATUS_COMMAND, ignoreCase = true)) STATUS_QUERY else trimmed
        messages += ChatMessage(Role.User, trimmed)
        isSending = true
        status = "送信中"
        error = null

        scope.launch {
            suspend fun send(accessToken: String) = client.sendMessage(
                backendUrl = backendUrl,
                accessToken = accessToken,
                threadId = threadId,
                messages = messages.dropLast(1) + ChatMessage(Role.User, outgoing),
            )

            try {
                status = "シグマリス応答中"
                val reply = try {
                    send(authManager.currentAccessToken())
                } catch (_: UnauthorizedException) {
                    send(authManager.currentAccessToken(forceRefresh = true))
                }
                threadId = reply.threadId
                if (reply.text.isNotBlank()) {
                    messages += ChatMessage(Role.Assistant, reply.text)
                    onSpeak(reply.text)
                }
                status = "待機中"
            } catch (_: NotLoggedInException) {
                error = "セッションが切れました。再ログインしてください。"
                status = "エラー"
                authManager.logout()
                onLoggedOut()
            } catch (exception: Exception) {
                error = exception.message ?: "送信に失敗しました。"
                status = "エラー"
            } finally {
                isSending = false
            }
        }
    }

    Scaffold(
        positionIndicator = { PositionIndicator(scalingLazyListState = listState) },
    ) {
        Box(
            modifier = Modifier
                .fillMaxSize()
                .background(Color(0xFF050505)),
        ) {
            ScalingLazyColumn(
                state = listState,
                modifier = Modifier.fillMaxSize(),
                contentPadding = PaddingValues(horizontal = 18.dp, vertical = 18.dp),
                horizontalAlignment = Alignment.CenterHorizontally,
                verticalArrangement = Arrangement.spacedBy(10.dp),
            ) {
                item {
                    Text(
                        text = "Sigmaris",
                        color = Color.White,
                        fontSize = 19.sp,
                        textAlign = TextAlign.Center,
                    )
                }
                item {
                    Text(
                        text = status,
                        color = Color(0xFFB7F7D5),
                        fontSize = 12.sp,
                        textAlign = TextAlign.Center,
                    )
                }
                item {
                    Button(
                        onClick = {
                            status = "聞き取り中"
                            error = null
                            onStartVoiceInput(
                                { spokenText -> submit(spokenText) },
                                { message ->
                                    error = message
                                    status = "エラー"
                                },
                            )
                        },
                        enabled = !isSending,
                        modifier = Modifier.size(76.dp),
                        colors = ButtonDefaults.buttonColors(
                            backgroundColor = Color(0xFF22C55E),
                            contentColor = Color.Black,
                        ),
                    ) {
                        Icon(
                            imageVector = Icons.Rounded.Mic,
                            contentDescription = "話す",
                            modifier = Modifier.size(32.dp),
                        )
                    }
                }
                item {
                    Chip(
                        onClick = { submit(STATUS_COMMAND) },
                        label = { Text("/status 認知状態確認", fontSize = 11.sp) },
                        colors = ChipDefaults.secondaryChipColors(),
                        modifier = Modifier.height(32.dp),
                    )
                }
                item {
                    SettingsFields(
                        backendUrl = backendUrl,
                        connectionStatus = connectionStatus,
                        onBackendUrlChange = {
                            saveBackendUrl(it)
                            connectionStatus = "未確認"
                        },
                        onCheckBackend = { checkBackend() },
                        onLogout = {
                            authManager.logout()
                            onLoggedOut()
                        },
                    )
                }
                if (error != null) {
                    item {
                        Bubble(
                            text = error.orEmpty(),
                            color = Color(0xFF4B1118),
                            textColor = Color(0xFFFFCDD2),
                        )
                    }
                }
                items(messages.size) { index ->
                    val message = messages[index]
                    MessageBubble(
                        message = message,
                        onSpeak = onSpeak,
                    )
                }
                item {
                    Spacer(modifier = Modifier.height(8.dp))
                }
            }
        }
    }
}

@Composable
private fun SettingsFields(
    backendUrl: String,
    connectionStatus: String,
    onBackendUrlChange: (String) -> Unit,
    onCheckBackend: () -> Unit,
    onLogout: () -> Unit,
) {
    Column(
        modifier = Modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(7.dp),
    ) {
        TinyInput(
            label = "Backend URL",
            value = backendUrl,
            onValueChange = onBackendUrlChange,
        )
        Chip(
            onClick = onCheckBackend,
            label = { Text("接続確認: $connectionStatus", fontSize = 11.sp) },
            colors = ChipDefaults.secondaryChipColors(),
            modifier = Modifier.height(34.dp),
        )
        Chip(
            onClick = onLogout,
            label = { Text("ログアウト", fontSize = 11.sp) },
            colors = ChipDefaults.secondaryChipColors(),
            modifier = Modifier.height(34.dp),
        )
    }
}

@Composable
private fun TinyInput(
    label: String,
    value: String,
    onValueChange: (String) -> Unit,
    isSecret: Boolean = false,
) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(12.dp))
            .background(Color(0xFF171717))
            .padding(horizontal = 10.dp, vertical = 7.dp),
    ) {
        Text(text = label, color = Color(0xFF8F8F8F), fontSize = 10.sp)
        BasicTextField(
            value = value,
            onValueChange = onValueChange,
            singleLine = true,
            visualTransformation = if (isSecret) PasswordVisualTransformation() else VisualTransformation.None,
            textStyle = TextStyle(color = Color.White, fontSize = 12.sp),
            modifier = Modifier.fillMaxWidth(),
        )
    }
}

@Composable
private fun MessageBubble(
    message: ChatMessage,
    onSpeak: (String) -> Unit,
) {
    val isUser = message.role == Role.User
    Column(
        modifier = Modifier.fillMaxWidth(),
        horizontalAlignment = if (isUser) Alignment.End else Alignment.Start,
    ) {
        Bubble(
            text = message.content,
            color = if (isUser) Color(0xFF262626) else Color(0xFF0F2E24),
            textColor = Color.White,
            alignRight = isUser,
        )
        if (!isUser) {
            Row(
                modifier = Modifier.padding(top = 4.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Chip(
                    onClick = { onSpeak(message.content) },
                    label = { Text("読む", fontSize = 11.sp) },
                    icon = {
                        Icon(
                            imageVector = Icons.Rounded.VolumeUp,
                            contentDescription = "読み上げ",
                            modifier = Modifier.size(14.dp),
                        )
                    },
                    colors = ChipDefaults.secondaryChipColors(),
                    modifier = Modifier.height(32.dp),
                )
            }
        }
    }
}

@Composable
private fun Bubble(
    text: String,
    color: Color,
    textColor: Color,
    alignRight: Boolean = false,
) {
    Box(
        modifier = Modifier
            .fillMaxWidth(if (alignRight) 0.84f else 0.96f)
            .clip(
                RoundedCornerShape(
                    topStart = 14.dp,
                    topEnd = 14.dp,
                    bottomStart = if (alignRight) 14.dp else 5.dp,
                    bottomEnd = if (alignRight) 5.dp else 14.dp,
                ),
            )
            .background(color)
            .padding(horizontal = 11.dp, vertical = 9.dp),
    ) {
        Text(
            text = text,
            color = textColor,
            fontSize = 12.sp,
            lineHeight = 17.sp,
        )
    }
}
