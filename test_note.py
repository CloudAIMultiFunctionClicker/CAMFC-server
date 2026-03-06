"""
笔记功能测试
"""

import json
import requests
import pyotp
from user_auth import create_new_user


def get_auth_headers(uuid, totp_key):
    """生成认证头"""
    totp = pyotp.TOTP(totp_key)
    return {
        "Id": uuid,
        "Totp": totp.now()
    }


def test_note_add(base_url, uuid, totp_key):
    """测试添加笔记"""
    print("\n1. 测试添加笔记...")
    headers = get_auth_headers(uuid, totp_key)

    note_uuid = "test-note-001"
    data = {"uuid": note_uuid, "title": "测试笔记"}

    response = requests.post(f"{base_url}/note/add", json=data, headers=headers)
    result = response.json()

    if response.status_code == 200 and result.get("success"):
        print(f"   添加成功: {result}")
        return note_uuid
    else:
        print(f"   添加失败: {result}")
        return None


def test_note_update(base_url, uuid, totp_key, note_uuid):
    """测试更新笔记"""
    print("\n2. 测试更新笔记...")
    headers = get_auth_headers(uuid, totp_key)

    data = {
        "uuid": note_uuid,
        "content": "这是更新后的内容",
        "title": "更新后的标题"
    }

    response = requests.post(f"{base_url}/note/update", json=data, headers=headers)
    result = response.json()

    if response.status_code == 200 and result.get("success"):
        print(f"   更新成功: {result}")
    else:
        print(f"   更新失败: {result}")


def test_note_query(base_url, uuid, totp_key):
    """测试查询笔记"""
    print("\n3. 测试查询笔记...")
    headers = get_auth_headers(uuid, totp_key)

    data = {"num": 10}

    response = requests.post(f"{base_url}/note/query", json=data, headers=headers)
    result = response.json()

    if response.status_code == 200 and result.get("success"):
        print(f"   查询成功: 共 {result.get('total')} 条笔记")
        for note in result.get("notes", []):
            print(f"   - {note.get('title')}: {note.get('content')[:20]}...")
    else:
        print(f"   查询失败: {result}")


def test_note_delete(base_url, uuid, totp_key, note_uuid):
    """测试删除笔记"""
    print("\n4. 测试删除笔记...")
    headers = get_auth_headers(uuid, totp_key)

    data = {"uuid": note_uuid}

    response = requests.post(f"{base_url}/note/delete", json=data, headers=headers)
    result = response.json()

    if response.status_code == 200 and result.get("success"):
        print(f"   删除成功: {result}")
    else:
        print(f"   删除失败: {result}")


def test_note_auth_fail(base_url, uuid, totp_key):
    """测试未授权访问"""
    print("\n5. 测试未授权访问...")

    data = {"uuid": "test", "title": "test"}

    response = requests.post(f"{base_url}/note/add", json=data)
    if response.status_code == 401:
        print(f"   未授权访问被正确拒绝")
    else:
        print(f"   警告: 未授权访问未被拒绝，状态码: {response.status_code}")


def main():
    base_url = "http://localhost:8005"
    print("开始测试笔记功能")
    print("=" * 50)

    print("创建测试用户...")
    uuid, totp_key = create_new_user()
    print(f"用户UUID: {uuid}")
    print(f"TOTP密钥: {totp_key}")

    note_uuid = test_note_add(base_url, uuid, totp_key)

    if note_uuid:
        test_note_update(base_url, uuid, totp_key, note_uuid)

    test_note_query(base_url, uuid, totp_key)

    if note_uuid:
        test_note_delete(base_url, uuid, totp_key, note_uuid)

    test_note_auth_fail(base_url, uuid, totp_key)

    print("\n" + "=" * 50)
    print("测试完成!")


if __name__ == "__main__":
    main()
