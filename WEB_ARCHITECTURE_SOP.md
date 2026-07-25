# 通用前后端交互 SOP（Web Architecture SOP）

> 适用对象：想理解「一般 software 前后端怎么对话」的开发者。
> 配套文档：`QUANT_RESEARCH_GUIDE.md`（量化研究路线）、`OPTIMIZATION_PLAN.md`（AlphaStream 优化清单）。
> 本文讲**通用范式**，不绑定某个项目。

---

## 0. 一张图看懂（标准请求-响应）

下图是一次完整的 REST 前后端交互：前端收集输入 → 发 HTTP 请求 → 后端路由/认证/业务/数据库 → 返回 JSON → 前端解析渲染。

```svg
<svg viewBox="0 0 680 420" width="100%" xmlns="http://www.w3.org/2000/svg" role="img" aria-labelledby="t">
  <defs>
    <marker id="arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
      <path d="M2 1L8 5L2 9" fill="none" stroke="context-stroke" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
    </marker>
  </defs>
  <title id="t">通用前后端交互流程</title>
  <desc>一次标准请求响应：前端收集输入、发 HTTP 请求，后端路由认证业务数据库处理后返回 JSON，前端解析渲染。</desc>

  <g>
    <rect x="220" y="20" width="240" height="56" rx="8" fill="#EEEDFE" stroke="#534AB7" stroke-width="0.5"/>
    <text x="340" y="42" text-anchor="middle" dominant-baseline="central" font-size="14" font-weight="500" fill="#26215C">前端</text>
    <text x="340" y="60" text-anchor="middle" dominant-baseline="central" font-size="13" fill="#5F5E5A">收集用户输入</text>
  </g>
  <line x1="340" y1="76" x2="340" y2="100" stroke="#534AB7" stroke-width="1.5" marker-end="url(#arrow)"/>

  <g>
    <rect x="220" y="100" width="240" height="56" rx="8" fill="#EEEDFE" stroke="#534AB7" stroke-width="0.5"/>
    <text x="340" y="122" text-anchor="middle" dominant-baseline="central" font-size="14" font-weight="500" fill="#26215C">前端</text>
    <text x="340" y="140" text-anchor="middle" dominant-baseline="central" font-size="13" fill="#5F5E5A">构造 HTTP 请求 (URL·method·JSON)</text>
  </g>
  <line x1="340" y1="156" x2="340" y2="180" stroke="#534AB7" stroke-width="1.5" marker-end="url(#arrow)"/>

  <g>
    <rect x="200" y="180" width="280" height="56" rx="8" fill="#E6F1FB" stroke="#185FA5" stroke-width="0.5"/>
    <text x="340" y="202" text-anchor="middle" dominant-baseline="central" font-size="14" font-weight="500" fill="#042C53">后端</text>
    <text x="340" y="220" text-anchor="middle" dominant-baseline="central" font-size="13" fill="#5F5E5A">路由 → 认证 → 业务 → 数据库</text>
  </g>
  <line x1="340" y1="236" x2="340" y2="260" stroke="#185FA5" stroke-width="1.5" marker-end="url(#arrow)"/>

  <g>
    <rect x="200" y="260" width="280" height="56" rx="8" fill="#E6F1FB" stroke="#185FA5" stroke-width="0.5"/>
    <text x="340" y="282" text-anchor="middle" dominant-baseline="central" font-size="14" font-weight="500" fill="#042C53">后端</text>
    <text x="340" y="300" text-anchor="middle" dominant-baseline="central" font-size="13" fill="#5F5E5A">返回 JSON (状态码 + 数据)</text>
  </g>
  <line x1="340" y1="316" x2="340" y2="340" stroke="#185FA5" stroke-width="1.5" marker-end="url(#arrow)"/>

  <g>
    <rect x="220" y="340" width="240" height="56" rx="8" fill="#EEEDFE" stroke="#534AB7" stroke-width="0.5"/>
    <text x="340" y="362" text-anchor="middle" dominant-baseline="central" font-size="14" font-weight="500" fill="#26215C">前端</text>
    <text x="340" y="380" text-anchor="middle" dominant-baseline="central" font-size="13" fill="#5F5E5A">解析 → 更新状态 → 渲染</text>
  </g>
</svg>
```

---

## 1. 核心模型：客户端-服务器 + API

任何软件的前后端，本质都是这两块通过**网络**对话：

- **前端（Client）**：浏览器网页 / 手机 App / 桌面程序。负责**展示 UI、收集用户输入**。用户只跟它打交道。
- **后端（Server）**：跑在服务器上的程序。负责**业务逻辑、算数据、存数据库**。用户看不见它。
- **API（接口）**：两者之间的「契约」——前端按约定发请求，后端按约定回数据。主流是 **HTTP/HTTPS + JSON**。

> 一句话：**前端是人机界面，后端是大脑，API 是它们之间的电话线。**

---

## 2. 主流交互范式（不止一种）

| 范式 | 怎么通信 | 典型场景 |
|---|---|---|
| **REST（请求-响应）** | 前端发 HTTP 请求，后端返回 JSON，**无状态** | 绝大多数 Web 应用（你两个项目都算这类） |
| **GraphQL** | 一个端点，前端自己声明要哪些字段 | 字段复杂、前端多变 |
| **WebSocket** | 双向长连接，服务器可主动推 | 聊天、行情、游戏（实时） |
| **SSR（服务端渲染）** | 后端直接吐完整 HTML | 传统 MVC / Next.js / 内容站 |
| **异步任务（带外回传）** | 触发后后台跑，结果走邮件/文件 | 重计算（AlphaStream 那种特例） |

**一般 software 默认指 REST 请求-响应**——下面 SOP 围绕它。

---

## 3. 必须懂的「契约」概念（面试/协作都考）

- **HTTP 方法语义**：`GET` 查 / `POST` 新建 / `PUT/PATCH` 改 / `DELETE` 删。别全用 POST。
- **状态码**：`2xx` 成功；`4xx` 是你（前端）的问题——`401` 没登录、`403` 没权限、`404` 没有、`422` 参数错；`5xx` 是服务器崩了。
- **数据格式**：`JSON` 是前后端通用语（`{"en":"...","zh":"..."}` 这种）。
- **认证**：`Token / JWT / Session-Cookie`——证明「你是谁」，每次请求带上。
- **CORS**：前端（localhost:5173）和后端（localhost:8000）不同源时，浏览器拦跨域请求，需后端放行（如 Vite proxy 或后端 `allow_origins`）。
- **无状态**：后端不记「上一秒是谁」，每次请求自带凭证。这样后端才能随便横向扩容。

---

## 4. 通用 SOP：设计一个前后端交互

### 阶段一：定接口契约（最关键，先写文档再写码）

- [ ] 列端点：`路径 + method + 入参 + 出参`（用 OpenAPI/Swagger 写清楚）
- [ ] 定状态码约定（成功 / 参数错 / 未授权 / 服务器错）
- [ ] 定认证方式（JWT？Session？）

### 阶段二：前端

- [ ] 收集并校验用户输入（格式错在前端就挡掉，别打后端）
- [ ] 构造请求（`fetch`/`axios` + URL + method + JSON body + 带 Token 头）
- [ ] 处理响应：成功 → 更新状态渲染；失败 → 按状态码给明确错误提示
- [ ] 管理三种状态：加载中 / 出错 / 空数据

### 阶段三：后端

- [ ] 路由匹配 `路径 + method`
- [ ] 中间件：CORS、认证、日志、限流
- [ ] 控制器：解析入参 → 调业务 → 拼响应
- [ ] 业务层 + 数据层：算 / 查 / 写库
- [ ] 返回统一结构（如 `{code, data, message}`）

### 阶段四：联调与安全

- [ ] 按契约联调（Postman 或前端真调）
- [ ] 错误全链路覆盖（前端崩 ≠ 后端崩，都要兜底）
- [ ] 安全：密钥不进代码、输入校验防注入、**全程 HTTPS**

---

## 5. 对照你手上的两个项目

| 项目 | 范式 | 位置 |
|---|---|---|
| **spoken-english-log** | 标准 REST 分离：React 前端 + FastAPI 后端 + JSON，Vite proxy `/api` | ✅ 主流范式，教科书级 |
| **AlphaStream** | 混合：FastAPI 返回 HTML + 一个异步 API + 邮件带外回传 | ⚠️ REST 特例（异步任务型），不是「一般 software」的典型 |

> 结论：你其实**已经在用一般范式了**——spoken-english-log 就是标准答案；AlphaStream 那个是「重计算场景」的特殊变种（前端触发、后端后台跑、结果走邮件带外回传，前端不轮询）。
