# -*- coding: utf-8 -*-
"""
JDBC 数据源自动配置脚本
自动在 WebLogic 域中创建 JDBC 数据源

用法:
    wlst.bat create_datasource.py [config.yaml路径]

作者: OSB 自动化工具
日期: 2026-05-13
"""

import sys
import os

# 简易 YAML 解析器（同 setup_jms.py）
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


def create_datasource(config):
    """创建 JDBC 数据源"""
    ds_name = get_nested(config, 'datasource', 'name', default='HrDS')
    ds_jndi = get_nested(config, 'datasource', 'jndi', default='jdbc/HrDS')
    db_type = get_nested(config, 'datasource', 'database_type', default='Oracle')
    db_url = get_nested(config, 'datasource', 'url', default='jdbc:oracle:thin:@localhost:1521:XE')
    db_user = get_nested(config, 'datasource', 'username', default='hr')
    db_pass = get_nested(config, 'datasource', 'password', default='hr')
    target = get_nested(config, 'datasource', 'target', default='DefaultServer')

    print("=== 创建 JDBC 数据源: %s ===" % ds_name)
    print("  JNDI: %s" % ds_jndi)
    print("  类型: %s" % db_type)
    print("  URL:  %s" % db_url)

    # 检查是否已存在
    try:
        cd('JDBCSystemResources')
        if exists(ds_name):
            print("  [SKIP] 数据源 '%s' 已存在" % ds_name)
            return
    except Exception:
        pass

    # 创建数据源
    cd('/')
    ds = cmo.createJDBCSystemResource(ds_name)
    jdbc_res = ds.getJDBCResource()
    jdbc_res.setJNDIName(ds_jndi)
    params = jdbc_res.getJDBCDataSourceParams()
    params.setURL(db_url)

    # 驱动属性
    driver_props = jdbc_res.getJDBCDriverParams()
    if db_type == 'Oracle':
        driver_props.setDriverName("oracle.jdbc.OracleDriver")
    elif db_type == 'MySQL':
        driver_props.setDriverName("com.mysql.cj.jdbc.Driver")
    else:
        driver_props.setDriverName("oracle.jdbc.OracleDriver")
    driver_props.setPassword(db_pass)

    # 连接属性
    conn_props = jdbc_res.getJDBCConnectionPoolParams()
    conn_props.setName(ds_name)
    conn_props.setUser(db_user)
    conn_props.setInitialCapacity(1)
    conn_props.setMaxCapacity(15)
    conn_props.setCapacityIncrement(1)
    conn_props.setShrinkFrequencySeconds(400)

    # 语句缓存
    stmt_cache = jdbc_res.getJDBCStatementParams()
    stmt_cache.setSQLStmtCacheSize(10)
    stmt_cache.setSQLStmtCacheSizePerTransaction(1)

    # 部署目标
    cd('/')
    linkTarget(getMBean('JDBCSystemResources/' + ds_name),
               getMBean('Server/' + target))

    print("  [OK] 数据源 '%s' 创建成功" % ds_name)


def main():
    print("=" * 60)
    print("OSB JDBC 数据源自动配置脚本")
    print("=" * 60)

    script_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
    if len(sys.argv) > 1:
        config_path = sys.argv[1]
    else:
        config_path = os.path.join(script_dir, '..', '..', 'config.yaml')
        if not os.path.exists(config_path):
            config_path = os.path.join(script_dir, 'config.yaml')

    config = read_config(config_path)

    admin_url = get_nested(config, 'global', 'admin_url', default='localhost:7101')
    admin_user = get_nested(config, 'global', 'admin_user', default='weblogic')
    admin_pass = get_nested(config, 'global', 'admin_password', default='weblogic')

    print("\n连接到 WebLogic 控制台: t3://%s" % admin_url)
    connect(admin_user, admin_pass, 't3://' + admin_url)
    edit()
    startEdit()

    try:
        create_datasource(config)
        save()
        activate(block="true")
        print("\n[OK] JDBC 数据源配置完成！")
    except Exception, e:
        print("\n[ERROR] 配置失败: %s" % str(e))
        discardChanges()
        raise
    finally:
        disconnect()


if __name__ == '__main__':
    main()
