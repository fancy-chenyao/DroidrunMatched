# App 使用 MobileService 插件集成与运行指南

本指南说明 `App` 如何集成并使用 `MobileService` 插件，包括工程配置、清单覆盖、运行方式与宿主交互示例。插件负责与服务端进行 WebSocket 连接、心跳维持以及交互式问答；宿主通过广播即可与插件交互，无需直接处理网络协议。<mccoremem id="03fk90nmxxsl459a6fxbdph00|03fnihomed6lfgb7s7c5zcrhb" />

---

## 环境要求
- 编译 SDK：33（与库一致）
- 最低 SDK：24
- Java：11
- 主要依赖：OkHttp 4.12.0（库已内置）
- 代码参考：
  - [MobileService/build.gradle.kts](DroidrunMatched/App/MobileService/build.gradle.kts)
  - [app/build.gradle.kts](DroidrunMatched/App/app/build.gradle.kts)
  - [settings.gradle.kts](DroidrunMatched/App/settings.gradle.kts)

---

## 集成步骤

### 1. 在 settings.gradle.kts 引入库模块

```kts
// settings.gradle.kts
include(":app")
include(":MobileService")
```

已在工程中配置，可直接使用：参见 [settings.gradle.kts](DroidrunMatched/App/settings.gradle.kts#L37-L41)。

### 2. 在 app/build.gradle.kts 添加依赖

```kts
dependencies {
    implementation(project(":MobileService"))
}
```

已在工程中配置：参见 [app/build.gradle.kts](DroidrunMatched/App/app/build.gradle.kts#L59-L62)。

### 3. 清单覆盖（可选）
MobileService 库清单中已注册初始化 Provider 与前台服务，并提供可覆盖的 meta-data：
- `AgentAutoStart`：是否在应用启动时自动启动插件服务（默认 `true`）
- `AgentHomeActivity`：宿主首页 Activity 的完整类名（默认 `com.example.emplab.MainActivity`）

无需在宿主显式声明 Provider/Service；仅在需要改变默认行为时于宿主 `application` 节点覆盖 meta-data：

```xml
<!-- App\MobileService\src\main\AndroidManifest.xml 的 <application> 节点内 -->
<meta-data
    android:name="AgentAutoStart"
    android:value="true" />
<meta-data
    android:name="AgentHomeActivity"
    android:value="com.example.emplab.MainActivity" />
```

参考库清单： [AndroidManifest.xml](DroidrunMatched/App/MobileService/src/main/AndroidManifest.xml)
插件在 Provider 创建阶段会自动注册 Activity 跟踪并根据 `AgentAutoStart` 判断是否启动服务。<mccoremem id="03fnihomed6lfgb7s7c5zcrhb" />

### 4. 权限检查
宿主需确保以下权限（工程已配置）：
- `INTERNET`
- `ACCESS_NETWORK_STATE`
- `FOREGROUND_SERVICE` 与 `FOREGROUND_SERVICE_DATA_SYNC`
- `SYSTEM_ALERT_WINDOW`（悬浮窗）

参考宿主清单： [app/AndroidManifest.xml](DroidrunMatched/App/app/src/main/AndroidManifest.xml#L4-L20)

### 5. 网络安全配置（开发模式）
为支持 WebSocket 明文 `ws://` 到本地/局域网地址，宿主已启用 `network_security_config` 的开发域名白名单：
- [network_security_config.xml](DroidrunMatched/App/app/src/main/res/xml/network_security_config.xml)
- 宿主 `application` 已引用： [AndroidManifest.xml](DroidrunMatched/App/app/src/main/AndroidManifest.xml#L22-L32)

生产环境应使用 `wss://` 并关闭明文通信。

---

## 运行与交互

### 自动启动与前台服务
- 应用启动时，初始化 Provider 会在主进程注册 `ActivityTracker` 并按 `AgentAutoStart` 自动启动前台服务。
- 插件服务在创建时注册两个广播动作：
  - `STRING_ACTION`：接收宿主发送的自然语言任务指令
  - `ANSWER_ACTION`：接收宿主的用户答复（用于交互式问答）
 参考实现： [MobileService.kt](DroidrunMatched/App/MobileService/src/main/java/Agent/MobileService.kt#L203-L214) 与常量定义 [MobileGPTGlobal.kt](DroidrunMatched/App/MobileService/src/main/java/Agent/MobileGPTGlobal.kt#L37-L46)。<mccoremem id="03fk90nmxxsl459a6fxbdph00" />

### 配置服务端地址（示例）
开发与真机网络环境不同，请按需修改：
- 模拟器访问宿主机：`WS_HOST_IP = "10.0.2.2"`
- 真机访问宿主机：将 `WS_HOST_IP` 改为宿主机局域网 IP（如 `192.168.1.100`）
文件位置： [MobileGPTGlobal.kt](DroidrunMatched/App/MobileService/src/main/java/Agent/MobileGPTGlobal.kt#L21-L29)

### 宿主：发送任务指令
示例代码（在任意 Activity/Context 中调用）：

```kotlin
import android.content.Context
import android.content.Intent
import Agent.MobileGPTGlobal

/**
 * 发送任务指令给 MobileService
 * @param context 上下文
 * @param instruction 自然语言任务目标，如“打开设置”
 */
fun sendAgentInstruction(context: Context, instruction: String) {
    val intent = Intent(MobileGPTGlobal.STRING_ACTION).apply {
        putExtra(MobileGPTGlobal.INSTRUCTION_EXTRA, instruction)
    }
    context.sendBroadcast(intent)
}
```

插件接收后会在需要时自动建立 WebSocket 连接并将指令封装为 `task_request` 发送给服务端。协议参考： [MessageProtocol.kt](DroidrunMatched/App/MobileService/src/main/java/Agent/MessageProtocol.kt#L78-L112)。<mccoremem id="03fk90nmxxsl459a6fxbdph00" />


### 手动启动服务（仅当禁用自动启动时）
如设置 `AgentAutoStart=false`，可在宿主手动启动：

```kotlin
import android.content.Context
import android.content.Intent
import android.os.Build
import Agent.MobileService

/**
 * 手动启动 MobileService 前台服务
 * @param context 上下文
 */
fun startAgentService(context: Context) {
    val intent = Intent(context, MobileService::class.java)
    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
        context.startForegroundService(intent)
    } else {
        context.startService(intent)
    }
}
```

---

## 消息与数据流（简述）
- 宿主广播指令 → 插件接收并确保连接 → 发送 `task_request` 到服务端
- 服务端下发命令 → 插件执行并通过 `command_response` 回传结果
- 服务端提出问题 → 宿主展示并收集用户答案 → 宿主广播答案 → 插件发送 `user_answer` 到服务端
协议类型定义参考： [MessageProtocol.kt](DroidrunMatched/App/MobileService/src/main/java/Agent/MessageProtocol.kt#L26-L40)。<mccoremem id="03fk90nmxxsl459a6fxbdph00" />

---

## 常见问题与排查
- 无法连接服务端：
  - 检查 `WS_HOST_IP/WS_PORT` 是否符合当前设备（模拟器/真机）网络环境
  - 开发模式下需允许明文：确认 `network_security_config` 与宿主清单引用
- 悬浮窗未显示：确认 `SYSTEM_ALERT_WINDOW` 权限
- 自动启动未生效：确认宿主是否覆盖了 `AgentAutoStart`；查看 Provider 是否在主进程初始化
- 首页判断异常：如使用自定义首页类名，请正确设置 `AgentHomeActivity`（完整类名）

---

## 代码位置参考
- 插件清单与初始化： [MobileService/AndroidManifest.xml](DroidrunMatched/App/MobileService/src/main/AndroidManifest.xml)
- 初始化 Provider： [AgentInitProvider.kt](DroidrunMatched/App/MobileService/src/main/java/Agent/AgentInitProvider.kt)
- 前台服务与广播接收： [MobileService.kt](DroidrunMatched/App/MobileService/src/main/java/Agent/MobileService.kt)
- 广播常量与网络配置： [MobileGPTGlobal.kt](DroidrunMatched/App/MobileService/src/main/java/Agent/MobileGPTGlobal.kt)
- 消息协议封装： [MessageProtocol.kt](DroidrunMatched/App/MobileService/src/main/java/Agent/MessageProtocol.kt)
- 宿主清单与网络安全： [app/AndroidManifest.xml](DroidrunMatched/App/app/src/main/AndroidManifest.xml)，[network_security_config.xml](DroidrunMatched/App/app/src/main/res/xml/network_security_config.xml)

