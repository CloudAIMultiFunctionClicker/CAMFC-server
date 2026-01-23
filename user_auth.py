"""
用户认证管理模块
用于管理UUID和TOTP密钥的对应关系
存储格式：{uuid: totp_raw_key} 的JSON文件
"""

import json,time
import os
import logging
from pathlib import Path
from typing import Dict, Optional
import uuid as uuid_lib

logger = logging.getLogger(__name__)

# 存储用户认证数据的文件路径
# 放在storage目录下，这样备份的时候能一起备份
USERS_FILE = Path(__file__).parent.absolute() / "storage" / "users.json"


def ensure_users_file() -> None:
    """确保用户数据文件存在，如果不存在就创建个空的"""
    if not USERS_FILE.parent.exists():
        USERS_FILE.parent.mkdir(parents=True, exist_ok=True)
        logger.debug(f"创建目录: {USERS_FILE.parent}")
    
    if not USERS_FILE.exists():
        # 先写个空的JSON对象进去
        with open(USERS_FILE, 'w', encoding='utf-8') as f:
            json.dump({}, f, indent=2)
        logger.info(f"创建空的用户数据文件: {USERS_FILE}")


def load_users() -> Dict[str, str]:
    """加载用户数据
    返回字典：{uuid: totp_raw_key}
    """
    ensure_users_file()
    
    try:
        with open(USERS_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # 做个类型检查，确保是字典格式
        if not isinstance(data, dict):
            logger.error(f"用户数据格式不对，期望字典但得到 {type(data)}")
            return {}
        
        return data
    except json.JSONDecodeError as e:
        logger.error(f"解析用户数据JSON失败: {e}")
        return {}
    except Exception as e:
        logger.error(f"读取用户数据文件失败: {e}")
        return {}


def save_users(users: Dict[str, str]) -> bool:
    """保存用户数据到文件
    返回是否成功
    """
    try:
        # 先确保文件存在
        ensure_users_file()
        
        # 写文件
        with open(USERS_FILE, 'w', encoding='utf-8') as f:
            json.dump(users, f, indent=2, ensure_ascii=False)
        
        logger.debug(f"用户数据已保存，共 {len(users)} 个用户")
        return True
    except Exception as e:
        logger.error(f"保存用户数据失败: {e}")
        return False


def get_user_key(uuid_str: str) -> Optional[str]:
    """根据UUID获取对应的TOTP密钥
    找不到就返回None
    """
    users = load_users()
    return users.get(uuid_str)


def add_user(uuid_str: str, totp_key: str) -> bool:
    """添加新用户
    如果UUID已存在会覆盖（可能不太安全，但先这样）
    """
    users = load_users()
    users[uuid_str] = totp_key
    return save_users(users)


def delete_user(uuid_str: str) -> bool:
    """删除用户
    返回是否成功删除了
    """
    users = load_users()
    
    if uuid_str in users:
        del users[uuid_str]
        if save_users(users):
            logger.info(f"已删除用户: {uuid_str}")
            return True
    
    return False


def create_new_user() -> tuple[str, str]:
    """创建新用户
    返回 (uuid, totp_key) 对
    """
    import pyotp
    
    # 生成UUID
    user_uuid = str(uuid_lib.uuid4())
    
    # 生成TOTP密钥（base32格式）
    # pyotp.random_base32() 会生成一个随机的base32字符串
    totp_key = pyotp.random_base32()
    
    # 保存到文件
    if add_user(user_uuid, totp_key):
        logger.info(f"创建新用户成功: uuid={user_uuid}")
        return user_uuid, totp_key
    else:
        # 如果保存失败，抛个异常
        raise RuntimeError("创建用户失败，保存用户数据时出错")


def verify_totp(uuid_str: str, totp_code: str) -> bool:
    """验证TOTP码是否正确
    根据UUID找到对应的密钥，然后验证TOTP码
    同时打印当前正确的TOTP码（仅用于调试！）
    """
    import utotp

    # 先获取用户的TOTP密钥
    totp_key = get_user_key(uuid_str)
    if not totp_key:
        logger.warning(f"验证失败：找不到UUID对应的用户: {uuid_str}")
        return False

    # 创建TOTP对象
    correct_code=utotp.generate_totp(totp_key,custume_time=time.time())
    
    last_code = utotp.generate_totp(totp_key,time_move=-30,custume_time=time.time())
    
    next_code = utotp.generate_totp(totp_key,time_move=30,custume_time=time.time())

    # 验证输入的TOTP码
    is_valid = (correct_code == totp_code)or (last_code == totp_code) or (next_code == totp_code)
    
    if correct_code == totp_code:
        logger.info(f"刚好")
    elif last_code == totp_code:
        logger.info(f"慢了一点点")
    elif next_code == totp_code:
        logger.info(f"快了一点点")

    if is_valid:
        logger.debug(f"TOTP验证通过: uuid={uuid_str}")
    else:
        logger.warning(f"TOTP验证失败: uuid={uuid_str}, 输入码={totp_code}, 正确码={correct_code}")
    logger.info('匹配的uuid : '+uuid_str)
    logger.info('收到的totp : '+str(totp_code))
    logger.info('正确的totp : '+str(correct_code))
    logger.info('\n')
    
    logger.info('上一个totp : '+str(last_code))
    logger.info('下一个totp : '+str(next_code))

    logger.warning(f"time:{time.time()}\ttotp:{correct_code}")
    
    return is_valid


# 测试代码，如果直接运行这个文件的话
if __name__ == "__main__":
    # 设置一下日志，方便看输出
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    
    print("=== 测试用户认证模块 ===")
    
    # 确保文件存在
    ensure_users_file()
    print(f"1. 用户数据文件: {USERS_FILE}")
    
    # 创建新用户
    try:
        uuid, key = create_new_user()
        print(f"2. 创建新用户成功:")
        print(f"   UUID: {uuid}")
        print(f"   TOTP密钥: {key}")
        
        # 用这个密钥生成一个TOTP对象来测试
        import pyotp
        totp = pyotp.TOTP(key)
        test_code = totp.now()  # 当前有效的TOTP码
        print(f"3. 当前有效的TOTP码: {test_code}")
        
        # 验证一下
        result = verify_totp(uuid, test_code)
        print(f"4. 验证TOTP码: {'通过' if result else '失败'}")
        
        # 再验证一个错误的码
        wrong_result = verify_totp(uuid, "000000")
        print(f"5. 验证错误TOTP码: {'通过' if wrong_result else '失败'}")
        
    except Exception as e:
        print(f"测试出错: {e}")
    
    print("=== 测试结束 ===")
