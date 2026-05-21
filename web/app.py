#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
OSB 自动化工具 Web 端
用户上传 WSDL + 填写配置 -> 一键生成产物 -> 下载 ZIP
"""
import html
import io
import os
import re
import secrets
import sys
import zipfile
import tempfile
import shutil
import yaml
from flask import Flask, render_template, request, jsonify, send_file

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

app = Flask(__name__)
UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024  # 10MB max


def sanitize_name(name):
    """移除 Windows 非法文件名字符，确保推断名可用作目录/文件名"""
    if not name:
        return name
    for ch in ['<', '>', ':', '"', '/', '\\', '|', '?', '*']:
        name = name.replace(ch, '')
    return name if name else 'MyService'


def safe_int(value, default=0):
    try:
        return int(value) if value is not None and value != '' else default
    except (ValueError, TypeError):
        return default


def extract_wsdl_info(wsdl_content, filename=''):
    """从 WSDL 文件内容提取关键信息 + 自动推断配置"""
    import re
    info = {}

    # === 直接从 WSDL 提取 ===
    ns_match = re.search(r'targetNamespace="([^"]+)"', wsdl_content)
    info['namespace'] = ns_match.group(1) if ns_match else ''

    binding_matches = re.findall(r'<wsdl:binding name="([^"]+)"', wsdl_content)
    info['binding_name'] = binding_matches[0] if binding_matches else ''

    # Match wsdl:port with name attribute anywhere in the tag, but not portType
    port_tag_matches = re.findall(r'<wsdl:port\s[^>]*name="([^"]+)"', wsdl_content)
    info['port_name'] = port_tag_matches[0] if port_tag_matches else ''

    op_matches = re.findall(r'<wsdl:operation name="([^"]+)"', wsdl_content)
    info['operations'] = list(dict.fromkeys(op_matches))

    addr_matches = re.findall(r'<(?:wsdlsoap|soap):address\s+location="([^"]+)"', wsdl_content)
    info['endpoint_uri'] = addr_matches[0] if addr_matches else ''

    # === 自动推断 ===
    # 服务名：优先 port_name，其次 binding_name 去掉 "Binding"，其次文件名
    if info['port_name']:
        info['inferred_service_name'] = info['port_name']
    elif info['binding_name']:
        name = info['binding_name']
        for suffix in ['SoapBinding', 'Binding']:
            if name.endswith(suffix):
                name = name[:-len(suffix)]
                break
        info['inferred_service_name'] = name
    else:
        base = os.path.splitext(filename)[0] if filename else 'MyService'
        info['inferred_service_name'] = base

    # 应用名：从 namespace 最后一段 + "SB"，如 http://server.webservice.jtg.com → jtgSB
    ns = info.get('namespace', '')
    if ns and not ns.startswith('urn:'):
        parts = ns.split('.')
        if len(parts) >= 2:
            app_base = parts[-2]  # 倒数第二段，通常是项目名
        else:
            app_base = parts[0]
        app_base = sanitize_name(app_base)
        if app_base:
            info['inferred_application_name'] = app_base.capitalize() + 'SB'
        else:
            info['inferred_application_name'] = info['inferred_service_name'] + 'SB'
    else:
        # urn: 格式的 namespace 无法提取有意义的域名，直接用服务名
        info['inferred_application_name'] = info['inferred_service_name'] + 'SB'

    # 模块路径：application_name/service_name
    svc = info['inferred_service_name']
    app = info['inferred_application_name']
    info['inferred_module_path'] = f"{app}/{svc}SB"

    # Business Service 名称：service_name + "Biz"
    info['inferred_business_service_name'] = info['inferred_service_name'] + 'Biz'

    # 包前缀：从 namespace 反转推断，如 http://server.webservice.jtg.com → com.jtg.webservice
    if info['namespace']:
        ns_parts = [p for p in info['namespace'].split('/')[-1].split('.') if p]
        if len(ns_parts) >= 2:
            reversed_parts = ns_parts[::-1][:3]
            if reversed_parts[0] == 'com':
                info['inferred_package_prefix'] = '.'.join(reversed_parts)
            else:
                info['inferred_package_prefix'] = 'com.' + '.'.join(reversed_parts)
        else:
            info['inferred_package_prefix'] = 'com.hand.hsp'
    else:
        info['inferred_package_prefix'] = 'com.hand.hsp'

    return info


def normalize_module_path(path):
    """标准化模块路径：去除尾部斜杠，如果以 OSB 标准子目录名结尾则去掉最后一层"""
    if not path:
        return ''
    path = path.rstrip('/')
    subdirs = ('ProxyServices', 'BusinessServices', 'Pipelines', 'WSDLs', 'Adapters', 'Schemas', 'Transformations')
    parts = path.split('/')
    if parts[-1] in subdirs:
        parts = parts[:-1]
    return '/'.join(parts) if parts else ''


def sanitize_for_xml(s):
    """Sanitize user input for safe XML embedding"""
    if s is None:
        return ''
    return str(s).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def build_config(form_data, wsdl_info, wsdl_file_path):
    """合并表单数据和 WSDL 自动提取的信息"""
    # Sanitize all user inputs
    safe_get = lambda key, default='': sanitize_for_xml(form_data.get(key, default))

    config = {
        'global': {
            'module_path': normalize_module_path(safe_get('module_path')),
            'prefix': safe_get('prefix', 'Hmw'),
        },
        'defaults': {
            'pipeline_template': safe_get('pipeline_template',
                'CommonSB/Hmw/PipelineTemplates/HspPptSoapEsbInfo'),
            'http': {
                'timeout': safe_int(form_data.get('timeout'), 0),
                'connection_timeout': safe_int(form_data.get('connection_timeout'), 0),
                'retry_count': safe_int(form_data.get('retry_count'), 0),
                'retry_interval': safe_int(form_data.get('retry_interval'), 30),
                'load_balancing': safe_get('load_balancing', 'round-robin'),
            },
        },
        'project': {
            'application_name': safe_get('application_name', 'MyAppSB'),
            'package_prefix': safe_get('package_prefix', 'com.hand.hsp'),
        },
        'services': [{
            'name': safe_get('service_name', 'MyService'),
            'type': 'http',
            'wsdl': {
                'source_path': wsdl_file_path,
                'binding_name': sanitize_for_xml(form_data.get('binding_name', wsdl_info.get('binding_name', ''))),
                'namespace': sanitize_for_xml(form_data.get('namespace', wsdl_info.get('namespace', ''))),
                'port_name': sanitize_for_xml(form_data.get('port_name', wsdl_info.get('port_name', ''))),
            },
            'security': {
                'provider_id': safe_get('provider_id', 'XACMLAuthorizer'),
            },
            'endpoint': {
                'uri': sanitize_for_xml(form_data.get('endpoint_uri', wsdl_info.get('endpoint_uri', ''))),
                'timeout': safe_int(form_data.get('timeout'), 0),
                'connection_timeout': safe_int(form_data.get('connection_timeout'), 0),
                'retry_count': safe_int(form_data.get('retry_count'), 0),
                'retry_interval': safe_int(form_data.get('retry_interval'), 30),
                'load_balancing': safe_get('load_balancing', 'round-robin'),
                'username': sanitize_for_xml(form_data.get('auth_username', '')),
                'password': sanitize_for_xml(form_data.get('auth_password', '')),
            },
            'operations': [{'name': sanitize_for_xml(op)} for op in form_data.get('operations_list', wsdl_info.get('operations', ['defaultOperation']))],
        }],
    }

    bs_name = safe_get('business_service_name')
    if bs_name:
        config['services'][0]['business_service_name'] = bs_name

    return config


def generate_project(config, output_dir, templates_dir):
    """核心生成逻辑（从 generate_project.py 提取）"""
    import copy
    from jinja2 import Environment, FileSystemLoader, make_logging_undefined

    env = Environment(
        loader=FileSystemLoader(templates_dir),
        trim_blocks=True,
        lstrip_blocks=True,
        undefined=make_logging_undefined(),
    )

    def render_template(template_name, context):
        template = env.get_template(template_name)
        return template.render(**context)

    def get_config_with_defaults(service, config):
        defaults = config.get('defaults', {})
        result = copy.deepcopy(service)
        for key in ['security', 'endpoint']:
            if key not in result or result[key] is None:
                result[key] = {}
            if key in defaults:
                for dk, dv in defaults[key].items():
                    if dk not in result[key]:
                        result[key][dk] = dv
        if 'http' in defaults:
            result.setdefault('endpoint', {})
            for hk, hv in defaults['http'].items():
                if hk not in result['endpoint']:
                    result['endpoint'][hk] = hv
        return result

    def write_content(base_dir, sub_dir, filename, content):
        if sub_dir:
            path = os.path.join(base_dir, sub_dir, filename)
        else:
            path = os.path.join(base_dir, filename)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(content)

    app_name = config['project']['application_name']
    services = config.get('services', [])
    results = []

    for service in services:
        svc_name = service['name']
        svc_type = service.get('type', 'http')
        project_name = svc_name + 'SB'
        user_module = normalize_module_path(config.get('global', {}).get('module_path', ''))
        if user_module:
            base_dir = os.path.join(output_dir, user_module)
        else:
            base_dir = os.path.join(output_dir, app_name, project_name)

        # 生成 application.xml
        write_content(base_dir, None, 'application.xml',
            render_template('application.xml.j2', {'application_name': app_name}))

        # 生成 pom.xml
        write_content(base_dir, None, 'pom.xml',
            render_template('pom.xml.j2', {
                'project_name': project_name,
                'application_name': app_name,
                'package_prefix': config['project'].get('package_prefix', 'com.hand.hsp'),
                'soa_home': config['project'].get('soa_home', ''),
            }))

        if svc_type == 'http':
            svc = get_config_with_defaults(service, config)
            wsdl_cfg = svc.get('wsdl', {})
            source_path = wsdl_cfg.get('source_path', '')
            module_path = normalize_module_path(config.get('global', {}).get('module_path', '')) or f"{app_name}/{project_name}"
            bs_name = svc.get('business_service_name', svc_name)
            proxy_name = svc_name + 'Proxy'
            wsdl_file_name = svc_name
            pipeline_name = svc_name + 'PP'

            # WSDL
            with open(source_path, 'r', encoding='utf-8-sig') as f:
                wsdl_content = f.read()
            # 统一换行符为 \n，去掉尾部空白
            wsdl_content = wsdl_content.replace('\r\n', '\n').rstrip()
            if '<con:wsdlEntry' in wsdl_content:
                wsdl_output = wsdl_content
            else:
                import re
                ns_match = re.search(r'targetNamespace="([^"]+)"', wsdl_content)
                target_ns = ns_match.group(1) if ns_match else ''
                wsdl_output = render_template('wsdl_entry.wsdl.j2', {
                    'wsdl_content': wsdl_content,
                    'target_namespace': target_ns,
                })
            write_content(base_dir, 'WSDLs', wsdl_file_name + '.WSDL', wsdl_output)

            # Proxy Service
            write_content(base_dir, 'ProxyServices', proxy_name + '.ProxyService',
                render_template('proxy_service_http.proxy.j2', {
                    'service_name': svc_name,
                    'proxy_name': proxy_name,
                    'pipeline_name': pipeline_name,
                    'project_name': project_name,
                    'module_path': module_path,
                    'package_prefix': config['project'].get('package_prefix', 'com.hand.hsp'),
                    'security': svc.get('security', {}),
                    'wsdl': {
                        'binding_name': wsdl_cfg.get('binding_name', svc_name + 'SoapBinding'),
                        'namespace': wsdl_cfg.get('namespace', ''),
                    },
                    'wsdl_file_name': wsdl_file_name,
                }))

            # Business Service
            write_content(base_dir, 'BusinessServices', bs_name + '.BusinessService',
                render_template('business_service_http.bix.j2', {
                    'service_name': svc_name,
                    'business_service_name': bs_name,
                    'project_name': project_name,
                    'module_path': module_path,
                    'package_prefix': config['project'].get('package_prefix', 'com.hand.hsp'),
                    'endpoint': svc.get('endpoint', {}),
                    'wsdl': {
                        'port_name': wsdl_cfg.get('port_name', svc_name),
                        'namespace': wsdl_cfg.get('namespace', ''),
                    },
                    'wsdl_file_name': wsdl_file_name,
                }))

            # Pipeline
            operations = svc.get('operations', [])
            if operations and isinstance(operations, list):
                first_op = operations[0] if isinstance(operations[0], dict) else {}
                operation_name = first_op.get('name', 'defaultOperation')
            else:
                operation_name = 'defaultOperation'

            write_content(base_dir, 'Pipelines', svc_name + 'PP.Pipeline',
                render_template('pipeline_http.pipeline.j2', {
                    'service_name': svc_name,
                    'business_service_name': bs_name,
                    'project_name': project_name,
                    'module_path': module_path,
                    'package_prefix': config['project'].get('package_prefix', 'com.hand.hsp'),
                    'operation_name': operation_name,
                    'pipeline_template': config.get('defaults', {}).get(
                        'pipeline_template', 'CommonSB/Hmw/PipelineTemplates/HspPptSoapEsbInfo'),
                    'wsdl': {
                        'binding_name': wsdl_cfg.get('binding_name', svc_name + 'SoapBinding'),
                        'namespace': wsdl_cfg.get('namespace', ''),
                    },
                    'wsdl_file_name': wsdl_file_name,
                }))

        results.append({'name': svc_name, 'project': project_name, 'path': base_dir})

    return results


def generate_export_info(base_dir, module_path, svc_name, bs_name, proxy_name, wsdl_file_name, pipeline_name):
    """生成 ExportInfo 元数据文件"""
    from datetime import datetime
    now = datetime.now().strftime('%a %b %d %H:%M:%S CST %Y')
    mod_slash = module_path
    mod_dollar = module_path.replace('/', '$')
    lines = []
    lines.append('<?xml version="1.0" encoding="UTF-8"?>')
    lines.append('<xml-fragment name="" version="v2" xmlns:imp="http://www.bea.com/wli/config/importexport">')
    lines.append('    <imp:properties>')
    lines.append('        <imp:property name="username" value="admin"/>')
    lines.append('        <imp:property name="description" value=""/>')
    lines.append('        <imp:property name="exporttime" value="%s"/>' % now)
    lines.append('        <imp:property name="productname" value="Oracle Service Bus"/>')
    lines.append('        <imp:property name="productversion" value="12.2.1.2.0"/>')
    lines.append('        <imp:property name="projectLevelExport" value="false"/>')
    lines.append('    </imp:properties>')
    lines.append('    <imp:exportedItemInfo instanceId="%s/Pipelines/%s" typeId="Pipeline">' % (mod_slash, pipeline_name))
    lines.append('        <imp:properties>')
    lines.append('            <imp:property name="representationversion" value="0"/>')
    lines.append('            <imp:property name="dataclass" value="com.bea.wli.sb.pipeline.config.impl.PipelineEntryDocumentImpl"/>')
    lines.append('            <imp:property name="isencrypted" value="false"/>')
    lines.append('            <imp:property name="jarentryname" value="%s/Pipelines/%s.Pipeline"/>' % (mod_slash, pipeline_name))
    lines.append('            <imp:property name="extrefs" value="PipelineTemplate$CommonSB$Hmw$PipelineTemplates$HspPptSoapEsbInfo"/>')
    lines.append('            <imp:property name="extrefs" value="BusinessService$%s$BusinessServices$%s"/>' % (mod_dollar, bs_name))
    lines.append('            <imp:property name="extrefs" value="WSDL$%s$WSDLs$%s"/>' % (mod_dollar, wsdl_file_name))
    lines.append('        </imp:properties>')
    lines.append('    </imp:exportedItemInfo>')
    lines.append('    <imp:exportedItemInfo instanceId="%s/BusinessServices/%s" typeId="BusinessService">' % (mod_slash, bs_name))
    lines.append('        <imp:properties>')
    lines.append('            <imp:property name="representationversion" value="0"/>')
    lines.append('            <imp:property name="dataclass" value="com.oracle.xmlns.servicebus.business.config.impl.BusinessServiceEntryDocumentImpl"/>')
    lines.append('            <imp:property name="isencrypted" value="false"/>')
    lines.append('            <imp:property name="jarentryname" value="%s/BusinessServices/%s.BusinessService"/>' % (mod_slash, bs_name))
    lines.append('            <imp:property name="extrefs" value="WSDL$%s$WSDLs$%s"/>' % (mod_dollar, wsdl_file_name))
    lines.append('        </imp:properties>')
    lines.append('    </imp:exportedItemInfo>')
    lines.append('    <imp:exportedItemInfo instanceId="%s/ProxyServices/%s" typeId="ProxyService">' % (mod_slash, proxy_name))
    lines.append('        <imp:properties>')
    lines.append('            <imp:property name="representationversion" value="0"/>')
    lines.append('            <imp:property name="dataclass" value="com.bea.wli.sb.services.impl.ProxyServiceEntryDocumentImpl"/>')
    lines.append('            <imp:property name="isencrypted" value="false"/>')
    lines.append('            <imp:property name="jarentryname" value="%s/ProxyServices/%s.ProxyService"/>' % (mod_slash, proxy_name))
    lines.append('            <imp:property name="extrefs" value="Pipeline$%s$Pipelines$%s"/>' % (mod_dollar, pipeline_name))
    lines.append('            <imp:property name="extrefs" value="WSDL$%s$WSDLs$%s"/>' % (mod_dollar, wsdl_file_name))
    lines.append('        </imp:properties>')
    lines.append('    </imp:exportedItemInfo>')
    lines.append('    <imp:exportedItemInfo instanceId="%s/WSDLs/%s" typeId="WSDL">' % (mod_slash, wsdl_file_name))
    lines.append('        <imp:properties>')
    lines.append('            <imp:property name="representationversion" value="0"/>')
    lines.append('            <imp:property name="dataclass" value="com.bea.wli.sb.resources.config.impl.WsdlEntryDocumentImpl"/>')
    lines.append('            <imp:property name="isencrypted" value="false"/>')
    lines.append('            <imp:property name="jarentryname" value="%s/WSDLs/%s.WSDL"/>' % (mod_slash, wsdl_file_name))
    lines.append('        </imp:properties>')
    lines.append('    </imp:exportedItemInfo>')
    lines.append('</xml-fragment>')
    export_content = '\n'.join(lines) + '\n'

    # 写入 ExportInfo — 放在 app_name 目录下
    export_path = os.path.join(base_dir, 'ExportInfo')
    os.makedirs(os.path.dirname(export_path), exist_ok=True)
    with open(export_path, 'w', encoding='utf-8') as f:
        f.write(export_content)


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/analyze-wsdl', methods=['POST'])
def analyze_wsdl():
    """分析上传的 WSDL 文件，自动提取配置信息"""
    if 'wsdl_file' not in request.files:
        return jsonify({'error': '未上传 WSDL 文件'}), 400

    wsdl_file = request.files['wsdl_file']
    if not wsdl_file.filename:
        return jsonify({'error': '文件名为空'}), 400

    # 校验文件扩展名
    _, ext = os.path.splitext(os.path.basename(wsdl_file.filename))
    if ext.lower() not in ('.wsdl', '.xml'):
        return jsonify({'error': f'不支持的文件类型: {ext}'}), 400

    # 使用随机文件名防止路径遍历
    safe_name = f"{secrets.token_hex(8)}{ext.lower()}"
    wsdl_path = os.path.join(UPLOAD_FOLDER, safe_name)
    wsdl_file.save(wsdl_path)

    with open(wsdl_path, 'r', encoding='utf-8-sig') as f:
        content = f.read()

    info = extract_wsdl_info(content, filename=wsdl_file.filename)
    info['filename'] = safe_name
    info['file_size'] = os.path.getsize(wsdl_path)

    return jsonify(info)


@app.route('/api/preview', methods=['POST'])
def preview():
    """预览生成产物摘要"""
    data = request.get_json()
    if not data:
        return jsonify({'error': '缺少请求参数'}), 400

    wsdl_filename = data.get('wsdl_filename', '')
    if not wsdl_filename:
        return jsonify({'error': '请先上传 WSDL 文件'}), 400

    wsdl_path = os.path.join(UPLOAD_FOLDER, os.path.basename(wsdl_filename))
    if not os.path.exists(wsdl_path):
        return jsonify({'error': 'WSDL 文件不存在'}), 404

    with open(wsdl_path, 'r', encoding='utf-8-sig') as f:
        wsdl_content = f.read()
    wsdl_info = extract_wsdl_info(wsdl_content, filename=wsdl_filename)

    config = build_config(data, wsdl_info, wsdl_path)
    svc = config['services'][0]
    app_name = config['project']['application_name']
    project_name = svc['name'] + 'SB'
    module_path = normalize_module_path(config['global'].get('module_path', '')) or project_name
    bs_name = svc.get('business_service_name', svc['name'])
    wsdl_file_name = svc['name']

    return jsonify({
        'application_name': app_name,
        'project_name': project_name,
        'module_path': module_path,
        'service_name': svc['name'],
        'business_service_name': bs_name,
        'proxy_name': svc['name'] + 'Proxy',
        'pipeline_name': svc['name'] + 'PP',
        'wsdl_file_name': wsdl_file_name + '.WSDL',
        'endpoint_uri': svc['endpoint']['uri'],
        'operations': [op['name'] if isinstance(op, dict) else op for op in svc['operations']],
        'security_provider': svc.get('security', {}).get('provider_id', ''),
        'auth_username': svc['endpoint'].get('username', ''),
        'files': [
            f"{app_name}/{project_name}/",
            f"  BusinessServices/{bs_name}.BusinessService",
            f"  Pipelines/{svc['name']}PP.Pipeline",
            f"  ProxyServices/{svc['name']}Proxy.ProxyService",
            f"  WSDLs/{wsdl_file_name}.WSDL",
        ],
    })


@app.route('/api/generate', methods=['POST'])
def generate():
    """根据表单配置 + 上传的 WSDL 生成产物"""
    data = request.get_json()
    if not data:
        return jsonify({'error': '缺少请求参数'}), 400

    # 获取上传的 WSDL 文件名
    wsdl_filename = data.get('wsdl_filename', '')
    if not wsdl_filename:
        return jsonify({'error': '请先上传 WSDL 文件'}), 400

    wsdl_path = os.path.join(UPLOAD_FOLDER, os.path.basename(wsdl_filename))
    if not os.path.exists(wsdl_path):
        return jsonify({'error': 'WSDL 文件不存在'}), 404

    # 读取 WSDL 获取自动信息
    with open(wsdl_path, 'r', encoding='utf-8-sig') as f:
        wsdl_content = f.read()
    wsdl_info = extract_wsdl_info(wsdl_content)

    # 构建配置
    config = build_config(data, wsdl_info, wsdl_path)

    # 保存到临时文件供 source_path 引用
    templates_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'templates', 'jinja2')
    tmp_dir = tempfile.mkdtemp()

    try:
        results = generate_project(config, tmp_dir, templates_dir)

        # 生成 ExportInfo
        svc = config['services'][0]
        svc_name = svc['name']
        app_name = config['project']['application_name']
        project_name = svc_name + 'SB'
        module_path = normalize_module_path(config.get('global', {}).get('module_path', '')) or f"{app_name}/{project_name}"
        bs_name = svc.get('business_service_name', svc_name)
        proxy_name = svc_name + 'Proxy'
        pipeline_name = svc_name + 'PP'
        wsdl_file_name = svc_name

        # ExportInfo 放在 tmp_dir 下，确保它能被打包到 JAR 根目录
        generate_export_info(tmp_dir, module_path, svc_name, bs_name,
                             proxy_name, wsdl_file_name, pipeline_name)

        # 打包 JAR
        jar_path = os.path.join(tmp_dir, 'osb_output.jar')
        with zipfile.ZipFile(jar_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            for root, dirs, files in os.walk(tmp_dir):
                for f in files:
                    if f in ('osb_output.jar', 'osb_output.zip'):
                        continue
                    full = os.path.join(root, f)
                    arc = os.path.relpath(full, tmp_dir)
                    zf.write(full, arc)

        # 清理临时 WSDL 文件
        if os.path.exists(wsdl_path):
            os.remove(wsdl_path)

        return send_file(
            jar_path,
            mimetype='application/java-archive',
            as_attachment=True,
            download_name='osb_output.jar',
        )
    except Exception as e:
        return jsonify({'error': f'生成失败: {str(e)}'}), 500
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8899))
    debug = os.environ.get('FLASK_DEBUG', 'false').lower() == 'true'
    app.run(host='127.0.0.1', port=port, debug=debug)
