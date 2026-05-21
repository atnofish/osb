# -*- coding: utf-8 -*-
"""
DBAdapter 服务器配置脚本
自动配置 DbAdapter 出站连接池，使 DBAdapter 能够访问数据库

涵盖步骤：
1. 保存 DbAdapter 部署计划
2. 更新 DbAdapter 的出站连接池配置
3. 添加新的出站连接实例

对应文档章节 2.2.4 服务器准备 + 2.2.5 服务部署

用法:
    wlst.bat configure_dbadapter.py [config.yaml路径]

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


def configure_outbound_connection(config):
    """配置 DbAdapter 出站连接池"""
    conn_jndi = get_nested(config, 'dbadapter', 'outbound_connection', 'jndi',
                           default='eis/DB/HrDS')
    ds_name = get_nested(config, 'dbadapter', 'outbound_connection', 'datasource_name',
                         default='jdbc/HrDS')
    platform = get_nested(config, 'dbadapter', 'outbound_connection', 'platform_class',
                          default='org.eclipse.persistence.platform.database.Oracle10Platform')
    seq_prealloc = get_nested(config, 'dbadapter', 'outbound_connection', 'sequence_preallocation_size',
                               default=50)
    batch_write = get_nested(config, 'dbadapter', 'outbound_connection', 'uses_batch_writing',
                              default=True)
    native_seq = get_nested(config, 'dbadapter', 'outbound_connection', 'uses_native_sequencing',
                             default=True)
    skip_lock = get_nested(config, 'dbadapter', 'outbound_connection', 'uses_skip_locking',
                            default=True)

    print("=== 配置 DbAdapter 出站连接池 ===")
    print("  JNDI: %s" % conn_jndi)
    print("  数据源: %s" % ds_name)

    # 导航到 DbAdapter 的出站连接池配置
    cd('AppDeployments/DbAdapter')
    cd('Configuration/Control')
    cd('ResourceAdapter/OutboundConnectionPool')

    # 检查是否已存在
    try:
        cd('ConnectionFactoryInstances/' + conn_jndi)
        print("  [SKIP] 出站连接 '%s' 已存在" % conn_jndi)
        return
    except Exception:
        pass

    # 创建新的出站连接实例
    print("  创建出站连接实例...")

    # 在连接工厂组 javax.resource.cci.ConnectionFactory 下创建新实例
    new_outbound_conn_pool_instance(conn_jndi)

    # 配置连接属性
    cd('AppDeployments/DbAdapter/Configuration/Control/ResourceAdapter/OutboundConnectionPool/' +
       'ConnectionFactoryInstances/' + conn_jndi)

    # 设置属性
    set('DataSourceName', ds_name)
    set('PlatformClassName', platform)
    set('SequencePreallocationSize', str(seq_prealloc))
    set('UsesBatchWriting', str(batch_write))
    set('UsesNativeSequencing', str(native_seq))
    set('UsesSkipLocking', str(skip_lock))

    print("  [OK] 出站连接 '%s' 配置完成" % conn_jndi)
    print("  属性列表:")
    print("    DataSourceName:    %s" % ds_name)
    print("    PlatformClassName: %s" % platform)
    print("    SequencePreallocationSize: %s" % seq_prealloc)
    print("    UsesBatchWriting:  %s" % batch_write)
    print("    UsesNativeSequencing: %s" % native_seq)
    print("    UsesSkipLocking:   %s" % skip_lock)


def save_deployment_plan(config, soa_home):
    """保存部署计划"""
    plan_path = os.path.join(soa_home, 'soa', 'soa', 'DBAdapter_Plan.xml')
    plan_dir = os.path.dirname(plan_path)

    print("\n=== 保存部署计划 ===")
    print("  路径: %s" % plan_path)

    if not os.path.exists(plan_dir):
        os.makedirs(plan_dir, exist_ok=True)

    # 使用 WLST 保存部署计划
    cd('AppDeployments/DbAdapter')
    saveDeploymentPlan(plan_path)

    print("  [OK] 部署计划已保存")
    return plan_path


def update_dbadapter(config, soa_home):
    """更新 DbAdapter 部署"""
    plan_path = os.path.join(soa_home, 'soa', 'soa', 'DBAdapter_Plan.xml')
    rar_path = os.path.join(soa_home, 'connectors', 'DbAdapter.rar')

    print("\n=== 更新 DbAdapter 部署 ===")
    print("  部署计划: %s" % plan_path)
    print("  RAR 文件: %s" % rar_path)

    try:
        cd('AppDeployments/DbAdapter')
        updateApplication(
            'DbAdapter',
            rar_path,
            planPath=plan_path
        )
        print("  [OK] DbAdapter 已更新")
    except Exception, e:
        print("  [WARN] 更新失败，可能需要手动在控制台更新: %s" % str(e))
        print("  [INFO] 手动操作步骤:")
        print("    1. 登录 WebLogic 控制台 localhost:7101/console")
        print("    2. 导航至 部署 -> DbAdapter -> 控制")
        print("    3. 点击 更新")
        print("    4. 指定部署计划路径: %s" % plan_path)


def main():
    print("=" * 60)
    print("OSB DbAdapter 服务器配置脚本")
    print("=" * 60)

    script_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
    if len(sys.argv) > 1:
        config_path = sys.argv[1]
    else:
        config_path = os.path.join(script_dir, '..', '..', 'config.yaml')

    config = read_config(config_path)

    admin_url = get_nested(config, 'global', 'admin_url', default='localhost:7101')
    admin_user = get_nested(config, 'global', 'admin_user', default='weblogic')
    admin_pass = get_nested(config, 'global', 'admin_password', default='weblogic')

    soa_home = get_nested(config, 'project', 'soa_home',
                          default='C:\\Oracle\\Jdeveloper12c\\SOA\\12.2.1.2.0')

    print("\n连接到 WebLogic 控制台: t3://%s" % admin_url)
    connect(admin_user, admin_pass, 't3://' + admin_url)
    edit()
    startEdit()

    try:
        configure_outbound_connection(config)
        save()
        activate(block="true")
        print("\n[OK] DbAdapter 配置完成！")
    except Exception, e:
        print("\n[ERROR] 配置失败: %s" % str(e))
        discardChanges()
        raise
    finally:
        disconnect()


if __name__ == '__main__':
    main()
