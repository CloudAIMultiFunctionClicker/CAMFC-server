"""
测试新的认证和存储系统
验证重构后的功能是否正常工作
"""

import json
import requests
import time
from user_auth import create_new_user
import pyotp

def test_authentication():
    """测试新的TOTP认证系统"""
    print("=== 测试新的TOTP认证系统 ===")
    
    # 创建测试用户
    print("1. 创建测试用户...")
    try:
        uuid, totp_key = create_new_user()
        print(f"   用户创建成功:")
        print(f"   UUID: {uuid}")
        print(f"   TOTP密钥: {totp_key}")
        
        # 生成当前有效的TOTP码
        totp = pyotp.TOTP(totp_key)
        current_totp = totp.now()
        print(f"   当前TOTP码: {current_totp}")
        
        # 测试 /test 端点
        print("\n2. 测试 /test 端点...")
        
        # 方法1: 使用JSON格式的Authorization头
        headers_json = {
            "Authorization": json.dumps({"Id": uuid, "Totp": current_totp})
        }
        
        try:
            response = requests.get("http://localhost:8005/test", headers=headers_json)
            print(f"   JSON格式认证: {'成功' if response.json().get('valid') else '失败'}")
            print(f"   响应: {response.json()}")
        except Exception as e:
            print(f"   请求失败: {e}")
        
        # 方法2: 使用自定义头
        headers_custom = {
            "Id": uuid,
            "Totp": current_totp
        }
        
        try:
            response = requests.get("http://localhost:8005/test", headers=headers_custom)
            print(f"   自定义头认证: {'成功' if response.json().get('valid') else '失败'}")
            print(f"   响应: {response.json()}")
        except Exception as e:
            print(f"   请求失败: {e}")
        
        # 测试错误的TOTP码
        print("\n3. 测试错误的TOTP码...")
        headers_wrong = {
            "Id": uuid,
            "Totp": "000000"  # 错误的TOTP码
        }
        
        try:
            response = requests.get("http://localhost:8005/test", headers=headers_wrong)
            print(f"   错误TOTP码: {'成功' if response.json().get('valid') else '失败'}")
            print(f"   响应: {response.json()}")
        except Exception as e:
            print(f"   请求失败: {e}")
        
        # 测试缺少认证头
        print("\n4. 测试缺少认证头...")
        try:
            response = requests.get("http://localhost:8005/test")
            print(f"   无认证头: {'成功' if response.json().get('valid') else '失败'}")
            print(f"   响应: {response.json()}")
        except Exception as e:
            print(f"   请求失败: {e}")
        
        return uuid, totp_key
        
    except Exception as e:
        print(f"测试失败: {e}")
        return None, None

def test_storage_structure():
    """测试存储目录结构"""
    print("\n=== 测试存储目录结构 ===")
    
    import os
    from pathlib import Path
    
    base_dir = Path(__file__).parent.absolute()
    storage_dir = base_dir / "storage"
    
    print(f"1. 基础存储目录: {storage_dir}")
    
    if storage_dir.exists():
        print(f"2. storage目录内容:")
        for item in storage_dir.iterdir():
            if item.is_dir():
                print(f"   📁 {item.name}/")
                # 如果是UUID目录，显示内容
                if len(item.name) == 36 and '-' in item.name:  # 简单的UUID格式检查
                    try:
                        for subitem in item.iterdir():
                            if subitem.is_dir():
                                print(f"      📁 {subitem.name}/")
                            else:
                                print(f"      📄 {subitem.name}")
                    except:
                        pass
            else:
                print(f"   📄 {item.name}")
    else:
        print(f"2. storage目录不存在")
    
    # 检查users.json
    users_file = storage_dir / "users.json"
    if users_file.exists():
        print(f"3. users.json存在，内容:")
        try:
            with open(users_file, 'r', encoding='utf-8') as f:
                users_data = json.load(f)
                print(f"   用户数量: {len(users_data)}")
                for user_uuid in list(users_data.keys())[:3]:  # 显示前3个用户
                    print(f"   - {user_uuid}: {users_data[user_uuid][:10]}...")
                if len(users_data) > 3:
                    print(f"   ... 还有 {len(users_data) - 3} 个用户")
        except Exception as e:
            print(f"   读取users.json失败: {e}")
    else:
        print(f"3. users.json不存在")

def main():
    """主测试函数"""
    print("开始测试重构后的认证和存储系统")
    print("=" * 50)
    
    # 首先确保服务器正在运行
    print("注意: 请确保服务器正在运行 (python main.py)")
    print("      测试将在3秒后开始...")
    time.sleep(3)
    
    # 测试认证系统
    uuid, totp_key = test_authentication()
    
    # 测试存储结构
    test_storage_structure()
    
    print("\n" + "=" * 50)
    print("测试完成!")
    
    if uuid and totp_key:
        print("\n测试用户信息:")
        print(f"UUID: {uuid}")
        print(f"TOTP密钥: {totp_key}")
        print("\n可用于进一步测试:")
        print(f"curl -H 'Id: {uuid}' -H 'Totp: [当前TOTP码]' http://localhost:8005/test")
        
        # 生成QR码信息（用于TOTP验证器）
        print("\nTOTP配置信息:")
        totp = pyotp.TOTP(totp_key)
        provisioning_uri = totp.provisioning_uri(name=f"test@{uuid[:8]}", issuer_name="CAMFC-Server")
        print(f"TOTP URI: {provisioning_uri}")
        print("注意: 可以将此URI导入到Google Authenticator等TOTP验证器中")

if __name__ == "__main__":
    main()
