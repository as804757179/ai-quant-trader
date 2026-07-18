# ADR-020：API 主体、契约与 WebSocket 治理

日期：2026-07-16  
状态：Accepted

## 背景

旧接口使用可选全局 API_KEY。未配置时所有 HTTP 写接口可匿名调用，浏览器会把 VITE_API_KEY 编译到静态资源，WebSocket 完全绕过鉴权。错误响应同时存在根级 envelope、detail 嵌套 envelope、FastAPI 422 数组和原始异常文本，客户端无法可靠区分拒绝、失败和空数据。

项目需要保留本地只读观察能力，但不得让匿名或浏览器共享密钥执行数据运维、人工复核、策略、风险、订单或券商操作。

## 决策

### 1. 身份与凭据

1. 新增 auth.principals、auth.api_credentials 和 auth.api_sessions。数据库只保存由 SECRET_KEY 派生 HMAC-SHA256 的凭据/会话/CSRF 摘要，不保存原始 Token。
2. 主体类型只允许 human 和 service；匿名开发只读主体不写入数据库，且不代表人工身份。
3. 浏览器不再注入 VITE_API_KEY。人工凭据只用于换取 HttpOnly、Secure（生产）、SameSite=Lax 会话 Cookie；写请求须提交服务端会话关联的 CSRF Token。
4. Worker 使用单独 service 主体和可轮换凭据；service_worker 默认不拥有 trade:submit 或 trade:cancel。
5. 旧 API_KEY 不再作为生产授权事实。若保留迁移桥接，只能在非生产环境显式打开，且不得用于高风险 Scope。

### 2. 角色与 Scope

固定最小角色：

- viewer：各领域只读。
- data_operator：行情同步、回填等数据运维。
- research_reviewer：研究人工复核。
- strategy_admin：策略版本管理。
- risk_admin：熔断和风险运维。
- trader：人工订单和撤单。
- auditor：审计与监控只读。
- service_worker：受控 AI 分析、筛选、回测和预检查。
- admin：显式全权限，仅用于受控本地管理。

Scope 使用 domain:action 格式。所有业务 Router 至少要求领域 read Scope；POST/管理接口额外要求具体 Scope。没有明确 Scope 的接口必须在路由账本校验中失败。

### 3. 开发与生产边界

1. health liveness 保持公开。
2. 仅 development 可启用匿名只读主体；匿名主体永不拥有任何 write、admin、review、submit、cancel 或 operate Scope。
3. production 不能启用匿名只读、旧 API_KEY 迁移桥接或公开 Docs；安全配置无效时应用启动失败。
4. 数据库认证存储不可用时，携带凭据的请求返回可识别的 503；不得回落为匿名或全局 Key。
5. metrics 需要 monitor:read，OpenAPI/Docs 在生产不公开。

### 4. WebSocket

1. WebSocket 只接受经过会话 Cookie 或 Authorization 凭据认证的主体，不接受 query token。
2. 握手必须校验 Origin 属于 ALLOWED_ORIGINS，缺失或不匹配均拒绝。
3. quotes、signals、alerts 和 portfolio 分别要求对应 read Scope；portfolio 额外按 mode/账户进一步收敛。
4. 所有事件后续带 event_version，连接、拒绝和断开写入关联日志；无仓内消费者的频道先保持兼容审查状态，不扩大订阅面。

### 5. HTTP 成功与失败契约

1. 成功响应统一保留 success、data、message、timestamp，并新增 request_id 与 contract_version。
2. 失败响应在根级返回 success=false、data=null、message、error_code、request_id、retryable 和可选 field_errors；不再嵌套 detail。
3. HTTPException、请求校验错误和未处理异常都经全局处理器转换；500/502/503 不返回底层异常文本。
4. 业务门禁拒绝必须是非 2xx 或根级 success=false，不能使用外层成功包裹内层失败。

## 后果

- 本地未登录用户仍可读取明确的开发观察接口，但不能执行任何写操作。
- 现有前端需要在 L6 迁移到会话和 CSRF；在此之前受保护写操作会正确显示未授权。
- 生产部署必须先通过脚本创建主体/凭据，否则私有 API 不可用；这是一种 fail-closed 配置状态。
- auth 相关接口、会话表和凭据表是旧接口治理的替代基础设施，不代表新增交易或研究业务能力。

## 验证

1. production 配置匿名读取或旧 Key 桥接时启动失败。
2. 匿名请求只能访问 development 只读 Scope，所有 POST 与管理路径被拒绝。
3. 无效、过期或撤销凭据，越权角色、缺失 CSRF、错误 Origin 和跨频道订阅均被拒绝。
4. 前端构建产物不含 VITE_API_KEY 运行时注入逻辑。
5. 401、403、422、500 和上游失败使用同一根级错误契约，且 request_id 可关联日志。

## 回滚

回滚只允许停止新会话签发和新凭据创建；已创建主体、凭据撤销记录、会话撤销记录和认证审计保留。生产环境不得以恢复匿名写或浏览器共享 Key 的方式回滚。若新认证路径故障，安全行为是拒绝高风险请求并保持六个交易/发布锁关闭。
