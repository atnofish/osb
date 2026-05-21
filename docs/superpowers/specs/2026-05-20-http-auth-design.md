# HTTP Basic Auth 支持 — 设计方案

## 背景

SAP 转换的 WebService 接口（如 `ZJT_SD003`）需要 HTTP Basic Authentication 才能调用。当前工具生成的 Business Service 配置缺少认证段，导致 JAR 导入 OSB 后无法通过认证调用 SAP 端点。

**WSDL 证据：** SAP 导出的 WSDL 中包含 `sp:HttpBasicAuthentication` 策略声明。

## 范围

- 仅支持 **HTTP Basic Authentication**
- 仅作用于 **Business Service 出站调用**（Proxy Service 入向不涉及）
- 用户名密码由用户在 Web 表单或 YAML 配置中手动填写

## 配置变更

在 `endpoint` 段增加两个可选字段：

```yaml
services:
  - name: SapZjtSd003
    type: http
    endpoint:
      uri: http://eccdgap01.jtgroup.com:8000/sap/bc/srt/rfc/sap/zjt_sd003/900/zjt_sd003/zjt_sd003
      username: JTOA
      password: 1971716
```

字段为空/不存在时，行为与当前一致（不渲染认证段）。

## 改动文件

| 文件 | 改动 |
|------|------|
| `templates/jinja2/business_service_http.bix.j2` | 在 `<http:outbound-properties>` 和 `<http:dispatch-policy>` 之间加有条件渲染的 `<http:authentication>` 段 |
| `web/app.py` | `build_config()` 收集 `username`/`password` 表单字段 |
| `python/generate_project.py` | `generate_business_service_http()` 将 `endpoint` 完整传入模板（已有） |
| `web/templates/index.html` | 在 endpoint 区域加"HTTP 认证"输入区 |

## 模板变更

```jinja2
{% if endpoint.username %}
<http:authentication>
    <http:basic-authentication>
        <http:username>{{ endpoint.username }}</http:username>
        <http:password>{{ endpoint.password }}</http:password>
    </http:basic-authentication>
</http:authentication>
{% endif %}
```

位置：`<http:outbound-properties>` 闭合标签之后，`<http:dispatch-policy>` 之前。

## Web 表单变更

在 endpoint 配置区域增加：
- 认证类型下拉：无 / Basic Auth
- 选中 Basic Auth 时显示用户名和密码输入框
- 不填时后端不传 `username`/`password`

## 不变的部分

- Proxy Service 模板 — 入向不需要认证
- Pipeline 模板 — 不涉端点连接
- WLST 脚本 — 与 JAR 生成无关
- 非 HTTP 类型服务（db_adapter/jms/file）— 不受影响

## 安全考虑

密码明文存储于配置和 JAR 中，与现有 `admin_password` 处理方式一致。后续可迁移至 WebLogic Credential Framework（方案 B）。

## 验收标准

1. Web 端上传 SAP WSDL，填写用户名密码 → 生成 JAR → 解压验证 `BusinessService` 包含 `<http:authentication>` 段
2. Web 端不填用户名密码 → 生成 JAR → 验证不包含认证段（向后兼容）
3. 命令行方式在 `config.yaml` 配置 `endpoint.username/password` → 生成产物同上
4. 非 HTTP 类型服务不受影响
