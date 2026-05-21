# -*- coding: utf-8 -*-
"""
JMS 初始化一键配置脚本
涵盖：持久性存储 -> JMS 服务器 -> JMS 模块 -> 子部署 -> 连接工厂 -> 队列 -> 主题 -> 更新 JMSAdapter

用法:
    在 JDeveloper 安装目录的 Oracle/Middleware/oracle_common/common/bin 下执行:
    wlst.bat setup_jms.py [config.yaml路径]

如果不传 config 路径，默认使用当前目录下的 config.yaml。

作者: OSB 自动化工具
日期: 2026-05-13
"""

import sys
import os

# ============================================================
# 简易 YAML 解析器（WLST 运行在 Jython 环境下，无 pyyaml）
# 只支持基础结构：key: value 和简单缩进
# ============================================================

def read_config(config_path):
    """读取 YAML 配置文件，返回嵌套字典"""
    config = {}
    if not os.path.exists(config_path):
        print("ERROR: 配置文件不存在: " + config_path)
        exit(1)

    stack = [(config, -1)]  # (dict, indent_level)

    with open(config_path, 'r', encoding='utf-8') as f:
        for line in f:
            stripped = line.rstrip()
            if not stripped or stripped.lstrip().startswith('#'):
                continue

            # 计算缩进
            indent = len(line) - len(line.lstrip())

            # 弹出栈中缩进更大的层级
            while len(stack) > 1 and stack[-1][1] >= indent:
                stack.pop()

            # 解析 key: value
            if ':' not in stripped.lstrip():
                continue
            key, _, value = stripped.lstrip().partition(':')
            key = key.strip()
            value = value.strip()

            # 去除行内注释
            if value and '#' in value:
                comment_idx = value.index('#')
                value = value[:comment_idx].strip()

            parent = stack[-1][0]

            if value:
                # 布尔值转换
                if value.lower() == 'true':
                    parent[key] = True
                elif value.lower() == 'false':
                    parent[key] = False
                elif value.isdigit():
                    parent[key] = int(value)
                else:
                    # 去除引号
                    if (value.startswith('"') and value.endswith('"')) or \
                       (value.startswith("'") and value.endswith("'")):
                        value = value[1:-1]
                    parent[key] = value
            else:
                # 空值表示字典
                new_dict = {}
                parent[key] = new_dict
                stack.append((new_dict, indent))

    return config


def get_nested(config, *keys, default=None):
    """安全获取嵌套字典值"""
    current = config
    for key in keys:
        if isinstance(current, dict) and key in current:
            current = current[key]
        else:
            return default
    return current


def apply_prefix(prefix, name):
    """如果名字不包含前缀则添加"""
    if name and not name.startswith(prefix):
        return prefix + name
    return name


# ============================================================
# JMS 配置函数
# ============================================================

def create_jdbc_store(config):
    """创建 JDBC 持久性存储"""
    js_name = get_nested(config, 'jms', 'jdbc_store', 'name', default='JDBCStore-Hmw')
    ds_name = get_nested(config, 'jms', 'jdbc_store', 'datasource', default='HrDS')
    tbl_prefix = get_nested(config, 'jms', 'jdbc_store', 'table_prefix', default='HMW2017')
    target = get_nested(config, 'jms', 'jdbc_store', 'target', default='DefaultServer')

    print("=== 创建 JDBC 持久性存储: %s ===" % js_name)

    cd('ServiceConfiguration/CustomResources/JDBCStore')
    if exists(js_name):
        print("  [SKIP] JDBCStore '%s' 已存在" % js_name)
        return

    cmo.createJDBCStore(js_name)
    cd('ServiceConfiguration/CustomResources/JDBCStore/' + js_name)
    set('StoreProperties', [
        jarray.array(['Prefix', 'TablePrefix', tbl_prefix], java.lang.String),
        jarray.array(['DataSourceName', 'JNDI', ds_name], java.lang.String)
    ])
    linkTarget(getMBean('ServiceConfiguration/CustomResources/JDBCStore/' + js_name),
               getMBean('Server/' + target))
    print("  [OK] JDBCStore '%s' 创建成功，数据源: %s，表前缀: %s" % (js_name, ds_name, tbl_prefix))


def create_jms_server(config):
    """创建 JMS 服务器"""
    js_name = get_nested(config, 'jms', 'jms_server', 'name', default='JMSServer-Hmw')
    store_name = get_nested(config, 'jms', 'jms_server', 'persistence_store', default='JDBCStore-Hmw')
    target = get_nested(config, 'jms', 'jms_server', 'target', default='DefaultServer')

    print("\n=== 创建 JMS 服务器: %s ===" % js_name)

    cd('ServiceConfiguration/JMSSystemResources')
    if exists(js_name):
        print("  [SKIP] JMS Server '%s' 已存在" % js_name)
        return

    jms_srv = cmo.createJMSServer(js_name)
    cd('ServiceConfiguration/JMSSystemResources/' + js_name)
    persist = jms_srv.getPersistenceStore()
    set('PersistenceStore', getMBean('ServiceConfiguration/CustomResources/JDBCStore/' + store_name))
    linkTarget(getMBean('ServiceConfiguration/JMSSystemResources/' + js_name),
               getMBean('Server/' + target))
    print("  [OK] JMS Server '%s' 创建成功，持久存储: %s" % (js_name, store_name))


def create_jms_module(config):
    """创建 JMS 系统模块"""
    mod_name = get_nested(config, 'jms', 'jms_module', 'name', default='SystemModule-Hmw')
    target = get_nested(config, 'jms', 'jms_module', 'target', default='DefaultServer')

    print("\n=== 创建 JMS 模块: %s ===" % mod_name)

    cd('AppDeployments/JMSModuleSystemResourceApplication/resource/JMSSystemResources')
    if exists(mod_name):
        print("  [SKIP] JMS Module '%s' 已存在" % mod_name)
        return

    cmo.createServerJMSSystemResource(mod_name)
    cd('AppDeployments/JMSModuleSystemResourceApplication/resource/JMSSystemResources/' + mod_name)
    linkTarget(getMBean('AppDeployments/JMSModuleSystemResourceApplication/resource/JMSSystemResources/' + mod_name),
               getMBean('Server/' + target))
    print("  [OK] JMS Module '%s' 创建成功" % mod_name)
    return mod_name


def create_sub_deployment(config, mod_name):
    """创建 JMS 子部署"""
    sd_name = get_nested(config, 'jms', 'sub_deployment', 'name', default='HmwSubModule')
    jms_srv = get_nested(config, 'jms', 'sub_deployment', 'jms_server', default='JMSServer-Hmw')
    module = get_nested(config, 'jms', 'sub_deployment', 'module', default=mod_name)

    print("\n=== 创建 JMS 子部署: %s ===" % sd_name)

    cd('AppDeployments/JMSModuleSystemResourceApplication/resource/JMSSystemResources/' + module)
    module_mbean = cmo.getModuleSystemResource()

    # 检查是否已存在
    sub_deployments = module_mbean.getSubDeployments()
    for sd in sub_deployments:
        if sd.getName() == sd_name:
            print("  [SKIP] 子部署 '%s' 已存在" % sd_name)
            return sd_name

    sub_dep = module_mbean.createSubDeployment(sd_name)
    sub_dep.addTarget(getMBean('JMSServer/' + jms_srv))
    print("  [OK] 子部署 '%s' 创建成功，目标: %s" % (sd_name, jms_srv))
    return sd_name


def create_connection_factory(config, mod_name):
    """创建 JMS 连接工厂"""
    cf_name = get_nested(config, 'jms', 'connection_factory', 'name', default='HmwConnectionFactory')
    cf_jndi = get_nested(config, 'jms', 'connection_factory', 'jndi', default='jms/HmwConnectionFactory')
    xa_enabled = get_nested(config, 'jms', 'connection_factory', 'xa_enabled', default=True)
    max_msg = get_nested(config, 'jms', 'connection_factory', 'max_messages_per_session', default=10)
    sd_name = get_nested(config, 'jms', 'connection_factory', 'sub_deployment', default='HmwSubModule')
    module = get_nested(config, 'jms', 'connection_factory', 'module', default=mod_name)

    print("\n=== 创建连接工厂: %s ===" % cf_name)

    cd('AppDeployments/JMSModuleSystemResourceApplication/resource/JMSSystemResources/' + module)
    module_mbean = cmo.getModuleSystemResource()

    # 检查是否已存在
    for cf in module_mbean.getConnectionFactories():
        if cf.getName() == cf_name:
            print("  [SKIP] 连接工厂 '%s' 已存在" % cf_name)
            return

    cf = module_mbean.createConnectionFactory(cf_name)
    cf.setJNDIName(cf_jndi)
    cf.setXAConnectionFactory(xa_enabled)
    cf.setMaxMessagesPerSession(max_msg)
    cf.setDeliveryFailureRetryPolicy(cmo.createDeliveryFailureRetryPolicy())

    # 分配到子部署
    sd = module_mbean.getSubDeployment(sd_name)
    cf.setSubDeployment(sd)
    print("  [OK] 连接工厂 '%s' 创建成功，JNDI: %s" % (cf_name, cf_jndi))


def create_queue(config, mod_name):
    """创建 JMS 队列"""
    q_name = get_nested(config, 'jms', 'queue', 'name', default='HmwQueue')
    q_jndi = get_nested(config, 'jms', 'queue', 'jndi', default='jms/HmwQueue')
    sd_name = get_nested(config, 'jms', 'queue', 'sub_deployment', default='HmwSubModule')
    module = get_nested(config, 'jms', 'queue', 'module', default=mod_name)

    print("\n=== 创建 JMS 队列: %s ===" % q_name)

    cd('AppDeployments/JMSModuleSystemResourceApplication/resource/JMSSystemResources/' + module)
    module_mbean = cmo.getModuleSystemResource()

    # 检查是否已存在
    for q in module_mbean.getQueues():
        if q.getName() == q_name:
            print("  [SKIP] 队列 '%s' 已存在" % q_name)
            return

    queue = module_mbean.createQueue(q_name)
    queue.setJNDIName(q_jndi)

    # 分配到子部署
    sd = module_mbean.getSubDeployment(sd_name)
    queue.setSubDeployment(sd)
    print("  [OK] 队列 '%s' 创建成功，JNDI: %s" % (q_name, q_jndi))


def create_topic(config, mod_name):
    """创建 JMS 主题（可选）"""
    enabled = get_nested(config, 'jms', 'topic', 'enabled', default=False)
    if not enabled:
        print("\n=== JMS 主题: 未启用，跳过 ===")
        return

    t_name = get_nested(config, 'jms', 'topic', 'name', default='HmwTopic')
    t_jndi = get_nested(config, 'jms', 'topic', 'jndi', default='jms/HmwTopic')
    sd_name = get_nested(config, 'jms', 'topic', 'sub_deployment', default='HmwSubModule')
    module = get_nested(config, 'jms', 'topic', 'module', default=mod_name)

    print("\n=== 创建 JMS 主题: %s ===" % t_name)

    cd('AppDeployments/JMSModuleSystemResourceApplication/resource/JMSSystemResources/' + module)
    module_mbean = cmo.getModuleSystemResource()

    for t in module_mbean.getTopics():
        if t.getName() == t_name:
            print("  [SKIP] 主题 '%s' 已存在" % t_name)
            return

    topic = module_mbean.createTopic(t_name)
    topic.setJNDIName(t_jndi)
    sd = module_mbean.getSubDeployment(sd_name)
    topic.setSubDeployment(sd)
    print("  [OK] 主题 '%s' 创建成功，JNDI: %s" % (t_name, t_jndi))


def update_jms_adapter(config):
    """更新 JMSAdapter 部署"""
    print("\n=== 更新 JMSAdapter ===")
    try:
        cd('AppDeployments/JmsAdapter')
        activate()
        print("  [OK] JMSAdapter 已更新")
    except Exception, e:
        print("  [WARN] JMSAdapter 更新跳过: %s" % str(e))


# ============================================================
# 主流程
# ============================================================

def main():
    print("=" * 60)
    print("OSB JMS 初始化自动配置脚本")
    print("=" * 60)

    # 读取配置
    script_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
    if len(sys.argv) > 1:
        config_path = sys.argv[1]
    else:
        config_path = os.path.join(script_dir, '..', '..', 'config.yaml')
        if not os.path.exists(config_path):
            config_path = os.path.join(script_dir, 'config.yaml')

    config = read_config(config_path)

    # 连接服务器
    admin_url = get_nested(config, 'global', 'admin_url', default='localhost:7101')
    admin_user = get_nested(config, 'global', 'admin_user', default='weblogic')
    admin_pass = get_nested(config, 'global', 'admin_password', default='weblogic')

    print("\n连接到 WebLogic 控制台: %s" % admin_url)
    connect(admin_user, admin_pass, 't3://' + admin_url)
    edit()
    startEdit()

    try:
        # 执行 8 步链路
        create_jdbc_store(config)        # 2.4.2 持久性存储
        create_jms_server(config)        # 2.4.3 JMS 服务器
        mod_name = create_jms_module(config)  # 2.4.4 JMS 模块
        create_sub_deployment(config, mod_name)  # 2.4.5 子部署
        create_connection_factory(config, mod_name)  # 2.4.6 连接工厂
        create_queue(config, mod_name)   # 2.4.7 队列
        create_topic(config, mod_name)   # 2.4.8 主题（可选）
        update_jms_adapter(config)       # 2.4.9 更新 JMSAdapter

        save()
        activate(block="true")

        print("\n" + "=" * 60)
        print("JMS 初始化配置完成！")
        print("=" * 60)

    except Exception, e:
        print("\n[ERROR] 配置失败: %s" % str(e))
        discardChanges()
        raise

    finally:
        disconnect()


if __name__ == '__main__':
    main()
