---
name: new-osb-service
description: 新增 OSB 服务 — 上传WSDL、解析配置、生成JAR包
disable-model-invocation: true
---

# 新增 OSB 服务

## 流程

1. 询问用户提供 WSDL 文件路径（本地文件或 URL）
2. 确认以下信息：
   - 服务名称（可从 WSDL 自动推断）
   - module_path（应用名/服务名SB）
   - 目标服务器（默认从 config.yaml 读取）
3. 启动 Web 端：
   ```bash
   cd E:/WorkSpace/osb-auto-config
   python web/app.py
   ```
4. 等待端口 8899 就绪（最多 30 秒重试检查）
5. 提示用户在浏览器打开 http://localhost:8899
6. 指导用户：上传 WSDL → 填写配置 → 生成 JAR → 下载
7. 完成后提醒用户：
   - 检查生成的 JAR 文件
   - 确认是否需要同步修改 generate_project.py 命令行版本
   - 是否需要同步两个入口的生成逻辑

## 注意事项

- web/app.py 和 python/generate_project.py 有独立生成逻辑，修改一个需要同步另一个
- 生成产物在 generated_projects/ 目录
- HTTP 类型服务与其他类型（db_adapter/jms/file）模板不同
