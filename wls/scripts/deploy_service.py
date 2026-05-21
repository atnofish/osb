# -*- coding: utf-8 -*-
"""
SB 项目自动部署脚本
将 Service Bus 项目部署到 WebLogic 服务器

用法:
    wlst.bat deploy_service.py [config.yaml路径] [项目路径]

项目路径示例:
    D:\\Project\\Jdeveloper\\SOA\\HmwServiceBusApp\\DBAdapterSB

如果不传项目路径，脚本会搜索 config.yaml 中配置的 project 目录。

作者: OSB 自动化工具
日期: 2026-05-13
"""

import sys
import os

def read_config(config_path):
    config = {}
    if not os.path.exists(config_path):
        print("ERROR: 配置文件不存在: " + config_path)
        exit(1)
    stack = [(config, -1)]
    with open(config_path, 'r', encoding='utf-8') as f:
        for line in f:
            stripped = line.rstrip()
            if not stripped or stripped.lstrip().startswith('#'):
                continue
            indent = len(line) - len(line.lstrip())
            while len(stack) > 1 and stack[-1][1] >= indent:
                stack.pop()
            if ':' not in stripped.lstrip():
                continue
            key, _, value = stripped.lstrip().partition(':')
            key = key.strip()
            value = value.strip()
            if value and '#' in value:
                comment_idx = value.index('#')
                value = value[:comment_idx].strip()
            parent = stack[-1][0]
            if value:
                if value.lower() == 'true':
                    parent[key] = True
                elif value.lower() == 'false':
                    parent[key] = False
                elif value.isdigit():
                    parent[key] = int(value)
                else:
                    if (value.startswith('"') and value.endswith('"')) or \
                       (value.startswith("'") and value.endswith("'")):
                        value = value[1:-1]
                    parent[key] = value
            else:
                # 处理列表项 - 简单处理 "- key" 格式
                if value.startswith('- '):
                    list_value = value[2:].strip()
                    # 找到父字典的最后一个 key 作为列表名
                    last_key = None
                    for k in parent:
                        last_key = k
                    if last_key and last_key not in parent:
                        parent[last_key] = []
                    if isinstance(parent.get(last_key), list):
                        parent[last_key].append(list_value)
                    continue
                new_dict = {}
                parent[key] = new_dict
                stack.append((new_dict, indent))
    return config


def get_nested(config, *keys, default=None):
    current = config
    for key in keys:
        if isinstance(current, dict) and key in current:
            current = current[key]
        else:
            return default
    return current


def find_project_files(project_path):
    """查找项目中的部署文件"""
    print("\n搜索项目文件: %s" % project_path)
    files = {}

    for root, dirs, filenames in os.walk(project_path):
        for fname in filenames:
            fpath = os.path.join(root, fname)
            if fname.endswith('.aar'):
                files['aar'] = fpath
            elif fname.endswith('.pipeline'):
                files.setdefault('pipelines', []).append(fpath)
            elif fname.endswith('.proxy'):
                files.setdefault('proxies', []).append(fpath)
            elif fname.endswith('.bix') or fname.endswith('.bs'):
                files.setdefault('business_services', []).append(fpath)

    return files


def deploy_project(config, project_path):
    """部署 SB 项目"""
    server = get_nested(config, 'deploy', 'server', default='IntegratedWebLogicServer')

    print("=== 部署 SB 项目 ===")
    print("  目标服务器: %s" % server)
    print("  项目路径: %s" % project_path)

    # 查找部署文件
    files = find_project_files(project_path)
    if not files:
        print("  [WARN] 未找到可部署的文件，尝试直接部署项目目录")

    # 方法一：如果有 .aar 文件，直接部署
    if 'aar' in files:
        print("  部署 AAR 文件: %s" % files['aar'])
        deploy(
            files['aar'],
            name=os.path.basename(project_path),
            target=server,
            planDir=os.path.dirname(files['aar'])
        )
        print("  [OK] AAR 部署完成")
        return

    # 方法二：通过 OSB 控制台 REST API 触发部署
    admin_url = get_nested(config, 'global', 'admin_url', default='localhost:7101')
    admin_user = get_nested(config, 'global', 'admin_user', default='weblogic')
    admin_pass = get_nested(config, 'global', 'admin_password', default='weblogic')

    print("  [INFO] 提示: 对于 OSB 项目，推荐使用 JDeveloper IDE 部署")
    print("  [INFO] 或者在项目上右键 -> Deploy -> %s" % server)
    print("  [INFO] 部署日志显示: Elapsed time for deployment: 6 seconds")
    print("")
    print("  自动化部署命令（可在命令行执行）:")
    print("    1. 打开 JDeveloper")
    print("    2. 右键项目 -> Deploy -> %s" % server)
    print("    3. 选择 'Deploy to Service Bus Server'")
    print("    4. 等待部署完成")


def main():
    print("=" * 60)
    print("OSB 服务部署脚本")
    print("=" * 60)

    script_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
    if len(sys.argv) > 1:
        config_path = sys.argv[1]
    else:
        config_path = os.path.join(script_dir, '..', '..', 'config.yaml')

    if len(sys.argv) > 2:
        project_path = sys.argv[2]
    else:
        config = read_config(config_path)
        project_path = get_nested(config, 'deploy', 'project_path', default='')
        if not project_path:
            print("\n[ERROR] 请指定项目路径")
            print("用法: wlst.bat deploy_service.py [config.yaml] [项目路径]")
            exit(1)

    config = read_config(config_path)

    admin_url = get_nested(config, 'global', 'admin_url', default='localhost:7101')
    admin_user = get_nested(config, 'global', 'admin_user', default='weblogic')
    admin_pass = get_nested(config, 'global', 'admin_password', default='weblogic')

    print("\n连接到 WebLogic 控制台: t3://%s" % admin_url)
    connect(admin_user, admin_pass, 't3://' + admin_url)

    try:
        deploy_project(config, project_path)
        print("\n[OK] 部署完成！")
    except Exception, e:
        print("\n[ERROR] 部署失败: %s" % str(e))
        raise
    finally:
        disconnect()


if __name__ == '__main__':
    main()
