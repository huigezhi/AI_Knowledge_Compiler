# Chrome 用户上手：照着点就行

不用理解架构，只要按顺序做完这 4 步。全程约 5 分钟，配一次，以后基本不用再管。

**你只需要记住两件事**：
1. 电脑上有个**后端程序**在跑（看不到界面，跑着就行）
2. Chrome 里装了个**扩展**，你所有操作都在它上面

---

## 第 1 步：让后端跑起来

打开文件夹 `E:\workbuddy_files\AI_Knowledge_Compiler\scripts\windows\`，**双击 `start.bat`**。

看到这样的输出就是成功了：

```
[AKC] 启动后端（端口 38127）
[OK ] 服务已就绪：http://127.0.0.1:38127/api/v1/health
     本地令牌文件：E:\...\apps\backend\data\auth_token
```

想自己确认一下，可以在 Chrome 地址栏打开：

```
http://127.0.0.1:38127/api/v1/health
```

看到 `{"status":"ok",...}` 就对了。

> 第一次使用（还没装依赖）要双击 `install.bat`，等它跑完再双击 `start.bat`。
>
> **想让以后开机自动跑** → 双击一次 `autostart.bat`。配完就不用再管第 1 步了。
>
> 它做的事情是在「**启动文件夹**」里放一个启动项（登录时自动拉起后端），
> **不需要管理员权限**。想取消就双击运行 `autostart.bat` 后按提示执行
> `akc.ps1 autostart -Off`，或直接删掉启动文件夹里的 `AKC Backend` 快捷方式。

---

## 第 2 步：在 Chrome 里装扩展

1. Chrome 地址栏输入 `chrome://extensions` 回车
2. 右上角把「**开发者模式**」开关打开
3. 左上角点「**加载已解压的扩展程序**」
4. 选择这个文件夹：
   ```
   E:\workbuddy_files\AI_Knowledge_Compiler\apps\extension\dist
   ```
   （**注意是 dist 文件夹**，不是 apps/extension）
5. 看到「AI Knowledge Compiler」卡片出现，就装好了
6. 建议点卡片上的**图钉**图标，把它固定到浏览器右上角工具栏

---

## 第 3 步：把令牌填进扩展（只做一次）

**为什么要令牌**：防止你在浏览别的网页时，那些网页偷偷往你的本地服务发请求。

1. 用记事本打开这个文件：
   ```
   E:\workbuddy_files\AI_Knowledge_Compiler\apps\backend\data\auth_token
   ```
   里面是一串乱码似的字符（约 43 位），**全选复制**

2. 在 Chrome 右上角**右键点击 AKC 扩展图标** → 选「**选项**」

3. 填两个框：
   | 字段 | 填什么 |
   | --- | --- |
   | 后端地址 | `http://127.0.0.1:38127` （默认就是，不用改） |
   | 本地访问令牌 | 刚才复制的那一串 |

4. 点「**测试连接**」→ 看到绿色的「已连接：v0.1.0 · schema 1.0.0」就成功了
5. 再点「**保存设置**」

> 如果点测试连接后提示"未授权访问"，说明填的地址不是本机地址，重新检查第 3 项。

---

## 第 4 步：开始采集

1. 打开 DeepSeek 网页版，**进入一个具体的对话**（不是首页）
2. 点浏览器右上角的 **AKC 扩展图标** → 侧边栏会打开
3. 侧边栏顶部会显示：
   ```
   平台       DeepSeek
   当前会话   （当前会话页）
   适配器     正常 · 已识别 12 轮对话
   ```
   **看到「正常」就可以用**。如果显示「降级/异常」，说明平台改了页面结构，告诉我，我来更新。
4. 点「**保存当前**」→ 对话就存进本地数据库了
5. 想顺便让 AI 提炼知识，点「**保存 + 编译**」（需要先配 Claude API Key，见下）

其它平台同理：ChatGPT、Claude、豆包、智谱清言，打开会话 → 点图标 → 保存。

**批量保存历史对话**：侧边栏点「加载」→ 勾选要同步的会话 → 点「批量同步」。

---

## 想看知识变成 Obsidian 笔记？

**第一步：连接你的 Obsidian 库（一键，不需要懂配置）**

双击：
```
E:\workbuddy_files\AI_Knowledge_Compiler\scripts\windows\set-vault.bat
```

它会**自动列出你电脑上已安装的 Obsidian 库**，你只要输入序号即可；也可以直接把库文件夹
拖到这个 bat 上，或者运行时粘贴路径。选好后它会自动写入配置并重启后端。

> 它只会在你的库里新建三个子目录（`01_Raw` 原始对话 / `03_Knowledge` 提炼的知识 /
> `02_Inbox`），**不会改动你已有的笔记**。
> 想换库：再运行一次；想取消连接：`akc.ps1 set-vault -Clear`。

连接是否成功，可以在扩展的**选项页**直接看到（有一行「Obsidian 知识库：已连接 …」）。

**第二步（可选）：配一个模型服务，AI 才会提炼知识**

**推荐用 DeepSeek**——国内直连、便宜，而且官方就提供 Claude 同款的接口协议，我们不用改代码就能接。

双击：
```
E:\workbuddy_files\AI_Knowledge_Compiler\scripts\windows\set-llm.bat
```

选 `1) DeepSeek` → 粘贴你的 Key（没有的话去 https://platform.deepseek.com/api_keys 申请）→ 回车。
它会**先发一个极小的请求实测这个 Key 能不能用**，通过后才写入配置并重启后端。

也可以手改 `apps\backend\.env`（记事本打开）：

```env
AKC_LLM_ENABLED=true                       # 想用 AI 编译就写 true
AKC_LLM_PROVIDER=deepseek                  # 决定接口地址；写 anthropic 就是 Claude
AKC_LLM_MODEL=deepseek-chat                # 模型名
AKC_LLM_API_KEY=sk-xxxx                    # 你的密钥
```

改完**重启后端**（双击 `stop.bat` 再 `start.bat`，或 `start-foreground.bat`）。

之后在侧边栏点「写入 Obsidian」，笔记就会出现：

```
01_Raw/DeepSeek/对话标题-2026-09-19.md      ← 原始对话
03_Knowledge/Methods/xxx.md                 ← AI 提炼的知识
```

> 不配 Claude 也能用：那就只会保存原始对话，不会生成提炼的知识笔记。

---

## 三个最常见的问题

| 现象 | 怎么办 |
| --- | --- |
| 侧边栏说「无法连接本地 AKC 服务」 | 后端没在跑 → 双击 `start.bat`；跑过了就点选项页的「测试连接」看具体报错 |
| 侧边栏说「未检测到会话」 | 你没在一个具体对话里（还在首页/列表页），点进任意一个对话再试 |
| 适配器显示「异常 · 未匹配到消息节点」 | 该平台的页面结构变了，需要更新适配器 → 见下方「跑一次结构探针」 |
| 保存时报 401 | 令牌错了 → 重新打开 `data\auth_token` 复制，粘贴到选项页保存 |

### 跑一次结构探针（适配器不匹配时）

不需要懂代码，照做即可：

1. 在那个平台的页面上按 **F12**，切到 **Console**（控制台）标签
2. 用记事本打开：
   ```
   E:\workbuddy_files\AI_Knowledge_Compiler\apps\extension\scripts\dom-probe.js
   ```
   **全选复制**里面的内容
3. 粘贴到 Console 里，回车
4. 它会自动把结果复制到剪贴板（并打印一段 JSON）→ 直接粘贴给维护者

探针**只输出页面结构**（标签名、class、data 属性），所有对话文字都被替换成 `{12字}` 这样的长度占位符，**不包含任何聊天内容**。

---

## 关于 VPS（先别看这段）

如果你的目标是「后端放到国外 VPS 上」，那上面第 3 步的后端地址要改成 VPS 地址，
还要在 VPS 上配 CORS —— 这部分有额外步骤，等你要做的时候单独找我，
我给你一条最省事的接法（SSH 隧道，扩展配置完全不用改）。
**在本机用的话，完全不需要关心这些。**
