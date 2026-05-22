#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
OSB 项目骨架生成器
根据 config.yaml 中的配置，自动生成完整的 Service Bus 项目结构

生成的项目结构：
    {application_name}/
    └── {project_name}/
        ├── Adapters/
        ├── BusinessServices/
        │   └── {service_name}.bix
        ├── Pipelines/
        │   └── {pipeline_name}.pipeline
        ├── ProxyServices/
        │   └── {proxy_name}.proxy
        ├── Schemas/
        ├── Transformations/
        ├── WSDLs/
        └── ExportInfo

用法:
    python generate_project.py [config.yaml路径] [输出目录]

作者: OSB 自动化工具
日期: 2026-05-13
"""

import io
import os
import sys
import copy
import re
import yaml
import shutil
from jinja2 import Environment, FileSystemLoader, make_logging_undefined

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')


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


def load_config(config_path):
    """加载 YAML 配置文件"""
    with open(config_path, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)
    if config is None:
        print("\n[ERROR] 配置文件为空: %s" % config_path)
        sys.exit(1)
    if not isinstance(config, dict):
        print("\n[ERROR] 配置文件格式错误（期望 YAML 映射）: %s" % config_path)
        sys.exit(1)
    return config


def get_config_with_defaults(service, config):
    """合并 defaults 段到服务配置，服务级别优先"""
    defaults = config.get('defaults', {})
    result = copy.deepcopy(service)

    for key in ['security', 'endpoint']:
        if key not in result or result[key] is None:
            result[key] = {}
        if key in defaults:
            for dk, dv in defaults[key].items():
                if dk not in result[key]:
                    result[key][dk] = dv

    # 合并 defaults.http -> service.endpoint
    if 'http' in defaults:
        result.setdefault('endpoint', {})
        for hk, hv in defaults['http'].items():
            if hk not in result['endpoint']:
                result['endpoint'][hk] = hv

    return result


def create_project_structure(output_dir, config, project_name):
    """创建项目目录结构"""
    app_name = config['project']['application_name']
    user_module = config.get('global', {}).get('module_path', '').rstrip('/')
    if user_module:
        base_dir = os.path.join(output_dir, user_module)
    else:
        base_dir = os.path.join(output_dir, app_name, project_name)
    dirs = [
        'Adapters',
        'BusinessServices',
        'Pipelines',
        'ProxyServices',
        'Schemas',
        'Transformations',
        'WSDLs',
    ]

    for d in dirs:
        dir_path = os.path.join(base_dir, d)
        os.makedirs(dir_path, exist_ok=True)

    return base_dir


def render_template(env, template_name, context):
    """渲染 Jinja2 模板"""
    template = env.get_template(template_name)
    return template.render(**context)


def generate_business_service(base_dir, service, global_prefix):
    """生成 BusinessService 文件"""
    svc_type = service.get('type', 'db_adapter')
    svc_name = service['name']

    context = {
        'service_name': svc_name,
        'service_type': svc_type,
        'transport_type': svc_type,
        'prefix': global_prefix,
    }

    if svc_type == 'jms':
        jms = service.get('jms', {})
        context.update({
            'transport_type': 'jms',
            'request_type': jms.get('request_type', 'Text'),
            'response_type': jms.get('response_type', 'None'),
            'endpoint_uri': jms.get('endpoint_uri', ''),
        })
        output = render_template(ENV, 'business_service.bix.j2', context)
        write_file(base_dir, 'BusinessServices', svc_name + '.BusinessService', output)

    elif svc_type == 'file':
        file_cfg = service.get('file', {})
        context.update({
            'transport_type': 'file',
            'request_type': file_cfg.get('request_type', 'Text'),
            'response_type': file_cfg.get('response_type', 'None'),
            'file_path': file_cfg.get('path', ''),
        })
        output = render_template(ENV, 'business_service.bix.j2', context)
        write_file(base_dir, 'BusinessServices', svc_name + '.BusinessService', output)

    elif svc_type == 'db_adapter':
        db = service.get('database', {})
        jca_context = {
            'service_name': svc_name,
            'connection': db.get('connection', 'HrDS'),
            'schema': db.get('schema', ''),
            'table': db.get('table', ''),
            'platform_class': 'org.eclipse.persistence.platform.database.Oracle10Platform',
            'sequence_preallocation_size': '10',
            'uses_native_sequencing': 'true',
            'uses_skip_locking': 'true',
        }
        output = render_template(ENV, 'adapter.jca.j2', jca_context)
        write_file(base_dir, 'Adapters', svc_name + '_db.jca', output)


def generate_pipeline(base_dir, service):
    """生成 Pipeline 文件"""
    svc_name = service['name']
    pipeline_name = svc_name + 'PP'

    context = {
        'pipeline_name': pipeline_name,
        'business_service_name': svc_name,
        'target_operation': 'defaultOperation',
    }
    output = render_template(ENV, 'pipeline.pipeline.j2', context)
    write_file(base_dir, 'Pipelines', pipeline_name + '.Pipeline', output)


def generate_proxy_service(base_dir, service, project_name):
    """生成 ProxyService 文件"""
    svc_name = service['name']
    proxy_name = svc_name + 'Proxy'
    pipeline_name = svc_name + 'PP'

    context = {
        'proxy_name': proxy_name,
        'pipeline_name': pipeline_name,
        'project_name': project_name,
        'transport_protocol': 'http',
        'wsdl_location': proxy_name,
        'binding': proxy_name + '-binding',
    }
    output = render_template(ENV, 'proxy_service.proxy.j2', context)
    write_file(base_dir, 'ProxyServices', proxy_name + '.ProxyService', output)


def generate_wsdl_from_source(base_dir, service):
    """从外部 WSDL 文件读取，用 CDATA 包裹或直接复制后写入"""
    svc_name = service.get('name')
    wsdl_cfg = service.get('wsdl', {})
    source_path = wsdl_cfg.get('source_path', '')

    if not source_path:
        raise ValueError("HTTP 服务缺少 wsdl.source_path: service=%s" % svc_name)

    if not os.path.exists(source_path):
        raise ValueError("WSDL 源文件不存在: %s" % source_path)

    with open(source_path, 'r', encoding='utf-8-sig') as f:
        wsdl_content = f.read()
    wsdl_content = wsdl_content.replace('\r\n', '\n').rstrip()

    # 使用服务名作为 WSDL 文件名
    wsdl_file_name = svc_name

    # 检测源文件是否已是 OSB 格式（包含 con:wsdlEntry）
    if '<con:wsdlEntry' in wsdl_content:
        # 已是 OSB 格式，直接复制
        output = wsdl_content
    else:
        # 裸 WSDL，用 CDATA 包裹
        ns_match = re.search(r'targetNamespace="([^"]+)"', wsdl_content)
        target_ns = ns_match.group(1) if ns_match else ''
        context = {
            'wsdl_content': wsdl_content,
            'target_namespace': target_ns,
        }
        output = render_template(ENV, 'wsdl_entry.wsdl.j2', context)

    write_file(base_dir, 'WSDLs', wsdl_file_name + '.WSDL', output)


def generate_proxy_service_http(base_dir, service, project_name, config):
    """生成 HTTP Proxy Service (OSB 格式)"""
    svc_name = service.get('name')
    proxy_name = service.get('proxy_name', svc_name + 'Proxy')
    pipeline_name = service.get('pipeline_name', svc_name + 'PP')
    security = service.get('security', {})
    wsdl_cfg = service.get('wsdl', {})
    wsdl_file_name = svc_name

    module_path = config.get('global', {}).get('module_path', '').rstrip('/') or project_name
    context = {
        'service_name': svc_name,
        'proxy_name': proxy_name,
        'pipeline_name': pipeline_name,
        'project_name': project_name,
        'module_path': module_path,
        'package_prefix': config['project'].get('package_prefix', 'com.hand.hsp'),
        'security': security,
        'endpoint': service.get('endpoint', {}),
        'wsdl': {
            'binding_name': wsdl_cfg.get('binding_name', svc_name + 'SoapBinding'),
            'namespace': wsdl_cfg.get('namespace', 'http://' + config['project'].get('package_prefix', 'com.hand.hsp') + '/' + svc_name),
        },
        'wsdl_file_name': wsdl_file_name,
    }
    output = render_template(ENV, 'proxy_service_http.proxy.j2', context)
    write_file(base_dir, 'ProxyServices', proxy_name + '.ProxyService', output)


def generate_business_service_http(base_dir, service, config, project_name):
    """生成 HTTP Business Service (OSB 格式)"""
    svc_name = service.get('name')
    bs_name = service.get('business_service_name', svc_name + 'Biz')
    endpoint = service.get('endpoint', {})
    wsdl_cfg = service.get('wsdl', {})
    wsdl_file_name = svc_name
    module_path = config.get('global', {}).get('module_path', '').rstrip('/') or project_name

    context = {
        'service_name': svc_name,
        'business_service_name': bs_name,
        'project_name': project_name,
        'module_path': module_path,
        'package_prefix': config['project'].get('package_prefix', 'com.hand.hsp'),
        'endpoint': endpoint,
        'wsdl': {
            'port_name': wsdl_cfg.get('port_name', svc_name),
            'namespace': wsdl_cfg.get('namespace', 'http://' + config['project'].get('package_prefix', 'com.hand.hsp') + '/' + svc_name),
        },
        'wsdl_file_name': wsdl_file_name,
        'service_account_name': module_path.split('/')[-1],
    }
    output = render_template(ENV, 'business_service_http.bix.j2', context)
    write_file(base_dir, 'BusinessServices', bs_name + '.BusinessService', output)

    # ServiceAccount（有认证凭据时生成）
    if endpoint.get('username'):
        acct_name = module_path.split('/')[-1] + 'ServiceAccount'
        acct_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<ser:service-account xsi:type="ser:StaticServiceAccount" '
            'xmlns:ser="http://www.bea.com/wli/sb/services" '
            'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
            'xmlns:con="http://www.bea.com/wli/sb/resources/config">\n'
            '    <ser:static-account>\n'
            '        <con:username>%s</con:username>\n'
            '        <con:password>%s</con:password>\n'
            '    </ser:static-account>\n'
            '</ser:service-account>\n' % (
                re.sub(r'[&<>]', lambda m: {'&':'&amp;','<':'&lt;','>':'&gt;'}[m.group()], endpoint['username']),
                re.sub(r'[&<>]', lambda m: {'&':'&amp;','<':'&lt;','>':'&gt;'}[m.group()], endpoint.get('password', '')),
            ))
        write_file(base_dir, 'Account', acct_name + '.ServiceAccount', acct_content)


def generate_pipeline_http(base_dir, service, config, project_name):
    """生成 HTTP Pipeline (OSB 格式)"""
    svc_name = service.get('name')
    bs_name = service.get('business_service_name', svc_name + 'Biz')
    operations = service.get('operations', [])
    if operations and isinstance(operations, list) and len(operations) > 0:
        first_op = operations[0] if isinstance(operations[0], dict) else {}
        operation_name = first_op.get('name', 'defaultOperation')
    else:
        operation_name = 'defaultOperation'
    wsdl_cfg = service.get('wsdl', {})
    wsdl_file_name = svc_name

    pipeline_template = config.get('defaults', {}).get(
        'pipeline_template',
        'CommonSB/Hmw/PipelineTemplates/HspPptSoapEsbInfo'
    )
    module_path = config.get('global', {}).get('module_path', '').rstrip('/') or project_name

    context = {
        'service_name': svc_name,
        'business_service_name': bs_name,
        'project_name': project_name,
        'module_path': module_path,
        'package_prefix': config['project'].get('package_prefix', 'com.hand.hsp'),
        'operation_name': operation_name,
        'pipeline_template': pipeline_template,
        'wsdl': {
            'binding_name': wsdl_cfg.get('binding_name', svc_name + 'SoapBinding'),
            'namespace': wsdl_cfg.get('namespace', 'http://' + config['project'].get('package_prefix', 'com.hand.hsp') + '/' + svc_name),
        },
        'wsdl_file_name': wsdl_file_name,
    }
    output = render_template(ENV, 'pipeline_http.pipeline.j2', context)
    write_file(base_dir, 'Pipelines', svc_name + 'PP.Pipeline', output)


def generate_wsdl(base_dir, service, config):
    """生成 WSDL 文件"""
    svc_name = service['name']
    svc_type = service.get('type', 'db_adapter')
    package_prefix = config['project'].get('package_prefix', 'com.hand.hsp')

    context = {
        'service_name': svc_name,
        'service_type': svc_type,
        'package_prefix': package_prefix,
        'target_namespace': 'http://' + package_prefix + '/' + svc_name,
    }

    if svc_type == 'db_adapter':
        db = service.get('database', {})
        context['operation_name'] = 'defaultOperation'
        context['table'] = db.get('table', '')
        context['schema'] = db.get('schema', '')
        context['endpoint_url'] = 'http://localhost:7001/' + svc_name

    elif svc_type == 'jms':
        jms = service.get('jms', {})
        context['operation_name'] = 'sendMessage'
        context['endpoint_url'] = jms.get('endpoint_uri', '')

    elif svc_type == 'file':
        file_cfg = service.get('file', {})
        context['operation_name'] = 'writeFile'
        context['endpoint_url'] = 'file://' + file_cfg.get('path', '')

    output = render_template(ENV, 'wsdl.wsdl.j2', context)
    write_file(base_dir, 'WSDLs', svc_name + '.WSDL', output)


def write_file(base_dir, sub_dir, filename, content):
    """写入文件"""
    if sub_dir:
        path = os.path.join(base_dir, sub_dir, filename)
    else:
        path = os.path.join(base_dir, filename)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)
    print("    生成: %s/%s" % (sub_dir, filename) if sub_dir else "    生成: %s" % filename)


def generate_export_info(base_dir, module_path, svc_name, bs_name, proxy_name, wsdl_file_name, pipeline_name, has_auth=False, pipeline_template=None):
    """生成 ExportInfo 元数据文件"""
    from datetime import datetime
    now = datetime.now().strftime('%a %b %d %H:%M:%S CST %Y')
    ts = int(datetime.now().timestamp() * 1000)
    acct_name = module_path.split('/')[-1] + 'ServiceAccount'

    # instanceId/jarentryname 用 / 分隔，extrefs 用 $ 分隔
    mod_slash = module_path
    mod_dollar = module_path.replace('/', '$')

    lines = []
    lines.append('<?xml version="1.0" encoding="UTF-8"?>')
    lines.append('<xml-fragment name="OSB-AUTO_build_%d" version="v2" xmlns:imp="http://www.bea.com/wli/config/importexport">' % ts)
    lines.append('    <imp:properties>')
    lines.append('        <imp:property name="username" value="ServiceBus"/>')
    lines.append('        <imp:property name="description" value=""/>')
    lines.append('        <imp:property name="exporttime" value="%s"/>' % now)
    lines.append('        <imp:property name="productname" value="Oracle Service Bus"/>')
    lines.append('        <imp:property name="productversion" value="12.2.1.2.0"/>')
    lines.append('        <imp:property name="projectLevelExport" value="false"/>')
    lines.append('    </imp:properties>')

    # Pipeline
    lines.append('    <imp:exportedItemInfo instanceId="%s/Pipelines/%s" typeId="Pipeline">' % (mod_slash, pipeline_name))
    lines.append('        <imp:properties>')
    lines.append('            <imp:property name="representationversion" value="0"/>')
    lines.append('            <imp:property name="dataclass" value="com.bea.wli.sb.pipeline.config.impl.PipelineEntryDocumentImpl"/>')
    lines.append('            <imp:property name="isencrypted" value="false"/>')
    lines.append('            <imp:property name="jarentryname" value="%s/Pipelines/%s.Pipeline"/>' % (mod_slash, pipeline_name))
    lines.append('            <imp:property name="extrefs" value="PipelineTemplate$%s"/>' % (pipeline_template or 'CommonSB/Hmw/PipelineTemplates/HspPptSoapEsbInfo').replace('/', '$'))
    lines.append('            <imp:property name="extrefs" value="BusinessService$%s$BusinessServices$%s"/>' % (mod_dollar, bs_name))
    lines.append('            <imp:property name="extrefs" value="WSDL$%s$WSDLs$%s"/>' % (mod_dollar, wsdl_file_name))
    lines.append('        </imp:properties>')
    lines.append('    </imp:exportedItemInfo>')

    # BusinessService
    lines.append('    <imp:exportedItemInfo instanceId="%s/BusinessServices/%s" typeId="BusinessService">' % (mod_slash, bs_name))
    lines.append('        <imp:properties>')
    lines.append('            <imp:property name="representationversion" value="0"/>')
    lines.append('            <imp:property name="dataclass" value="com.oracle.xmlns.servicebus.business.config.impl.BusinessServiceEntryDocumentImpl"/>')
    lines.append('            <imp:property name="isencrypted" value="false"/>')
    lines.append('            <imp:property name="jarentryname" value="%s/BusinessServices/%s.BusinessService"/>' % (mod_slash, bs_name))
    if has_auth:
        lines.append('            <imp:property name="extrefs" value="ServiceAccount$%s$Account$%s"/>' % (mod_dollar, acct_name))
    lines.append('            <imp:property name="extrefs" value="WSDL$%s$WSDLs$%s"/>' % (mod_dollar, wsdl_file_name))
    lines.append('        </imp:properties>')
    lines.append('    </imp:exportedItemInfo>')

    if has_auth:
        lines.append('    <imp:exportedItemInfo instanceId="%s/Account/%s" typeId="ServiceAccount">' % (mod_slash, acct_name))
        lines.append('        <imp:properties>')
        lines.append('            <imp:property name="representationversion" value="0"/>')
        lines.append('            <imp:property name="dataclass" value="com.bea.wli.sb.svcacct.StaticServiceAccountConfig"/>')
        lines.append('            <imp:property name="isencrypted" value="false"/>')
        lines.append('            <imp:property name="jarentryname" value="%s/Account/%s.ServiceAccount"/>' % (mod_slash, acct_name))
        lines.append('        </imp:properties>')
        lines.append('    </imp:exportedItemInfo>')

    # ProxyService
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

    # WSDL
    lines.append('    <imp:exportedItemInfo instanceId="%s/WSDLs/%s" typeId="WSDL">' % (mod_slash, wsdl_file_name))
    lines.append('        <imp:properties>')
    lines.append('            <imp:property name="representationversion" value="0"/>')
    lines.append('            <imp:property name="dataclass" value="com.bea.wli.sb.resources.config.impl.WsdlEntryDocumentImpl"/>')
    lines.append('            <imp:property name="isencrypted" value="false"/>')
    lines.append('            <imp:property name="jarentryname" value="%s/WSDLs/%s.WSDL"/>' % (mod_slash, wsdl_file_name))
    lines.append('        </imp:properties>')
    lines.append('    </imp:exportedItemInfo>')

    lines.append('</xml-fragment>')

    write_file(base_dir, None, 'ExportInfo', '\n'.join(lines) + '\n')


# 全局模板环境
TEMPLATES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'templates', 'jinja2')
ENV = Environment(
    loader=FileSystemLoader(TEMPLATES_DIR),
    trim_blocks=True,
    lstrip_blocks=True,
    undefined=make_logging_undefined(),
)

if not os.path.isdir(TEMPLATES_DIR):
    print("\n[ERROR] 模板目录不存在: %s" % TEMPLATES_DIR)
    sys.exit(1)


def main():
    print("=" * 60)
    print("OSB 项目骨架生成器")
    print("=" * 60)

    # 参数解析
    script_dir = os.path.dirname(os.path.abspath(__file__))
    if len(sys.argv) > 1:
        config_path = sys.argv[1]
    else:
        config_path = os.path.join(script_dir, '..', 'config.yaml')

    if len(sys.argv) > 2:
        output_dir = sys.argv[2]
    else:
        output_dir = os.path.join(script_dir, '..', 'generated_projects')

    if not os.path.exists(config_path):
        print("\n[ERROR] 配置文件不存在: %s" % config_path)
        sys.exit(1)

    config = load_config(config_path)

    # 配置验证
    if 'project' not in config:
        print("\n[ERROR] 配置文件缺少 'project' 段")
        sys.exit(1)
    if 'application_name' not in config['project']:
        print("\n[ERROR] project 段缺少 'application_name'")
        sys.exit(1)

    global_prefix = config.get('global', {}).get('prefix', 'Hmw')

    print("\n配置信息:")
    print("  Application: %s" % config['project']['application_name'])
    print("  前缀: %s" % global_prefix)
    print("  输出目录: %s" % output_dir)
    print("  服务数量: %d" % len(config.get('services', [])))

    # 如果没有指定 project_name，使用第一个服务的名字
    services = config.get('services', [])
    if not services:
        print("\n[ERROR] 配置文件中没有定义 services")
        sys.exit(1)

    # 为每个服务类型生成独立项目
    for service in services:
        svc_name = service.get('name')
        if not svc_name:
            print("\n[ERROR] services 列表中某项缺少 name 字段: %s" % str(service))
            sys.exit(1)

        svc_type = service.get('type', 'unknown')
        print("\n--- 生成服务: %s (类型: %s) ---" % (svc_name, svc_type))

        project_name = svc_name + 'SB'

        base_dir = create_project_structure(output_dir, config, project_name)
        print("  项目目录: %s" % base_dir)

        if svc_type == 'http':
            try:
                service_with_defaults = get_config_with_defaults(service, config)
                generate_wsdl_from_source(base_dir, service_with_defaults)
                generate_proxy_service_http(base_dir, service_with_defaults, project_name, config)
                generate_business_service_http(base_dir, service_with_defaults, config, project_name)
                generate_pipeline_http(base_dir, service_with_defaults, config, project_name)

                # 生成 ExportInfo
                app_name = config['project']['application_name']
                module_path = normalize_module_path(config.get('global', {}).get('module_path', '')) or f"{app_name}/{project_name}"
                bs_name = service_with_defaults.get('business_service_name', svc_name + 'Biz')
                has_auth = bool(service_with_defaults.get('endpoint', {}).get('username'))
                pipeline_template = config.get('defaults', {}).get(
                    'pipeline_template', 'CommonSB/Hmw/PipelineTemplates/HspPptSoapEsbInfo')
                generate_export_info(base_dir, module_path, svc_name, bs_name,
                                     svc_name + 'Proxy', svc_name, svc_name + 'PP', has_auth, pipeline_template)
            except ValueError as e:
                print("  [ERROR] %s — 跳过该服务" % e)
                continue
        elif svc_type == 'db_adapter':
            generate_business_service(base_dir, service, global_prefix)
            generate_pipeline(base_dir, service)
            generate_proxy_service(base_dir, service, project_name)
            generate_wsdl(base_dir, service, config)
        elif svc_type in ('jms', 'file'):
            generate_business_service(base_dir, service, global_prefix)
            generate_pipeline(base_dir, service)
            generate_proxy_service(base_dir, service, project_name)
            generate_wsdl(base_dir, service, config)
        else:
            print("  [WARN] 未知服务类型: %s，跳过" % svc_type)

    print("\n" + "=" * 60)
    print("项目骨架生成完成！")
    print("输出目录: %s" % output_dir)
    print("=" * 60)


if __name__ == '__main__':
    main()
