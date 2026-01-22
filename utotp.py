# TOTP验证码生成库（兼容MicroPython/标准Python）

try:
    import ustruct as struct
    from uhashlib import sha1
    from utime import time
except ImportError:
    # 非MicroPython环境（标准Python）
    import struct
    from hashlib import sha1
    from time import time

# 补充缺失的类型定义（修复b32encode中的报错）
bytes_types = (bytes, bytearray)


class Sha1HMAC:
    def __init__(self, key, msg=None):
        def translate(d, t):
            return bytes(t[x] for x in d)

        _trans_5C = bytes((x ^ 0x5C) for x in range(256))
        _trans_36 = bytes((x ^ 0x36) for x in range(256))
        self.digest_cons = sha1
        self.outer = self.digest_cons()
        self.inner = self.digest_cons()
        self.digest_size = 20
        self.blocksize = 64
        
        # 处理密钥长度（超过块大小则哈希）
        if len(key) > self.blocksize:
            key = self.digest_cons(key).digest()
        key = key + bytes(self.blocksize - len(key))
        
        self.outer.update(translate(key, _trans_5C))
        self.inner.update(translate(key, _trans_36))
        
        if msg is not None:
            self.update(msg)

    def update(self, msg):
        self.inner.update(msg)

    def _current(self):
        self.outer.update(self.inner.digest())
        return self.outer

    def digest(self):
        return self._current().digest()


# 固定测试时间：2026年1月1日 00:00:00 UTC
TEST_TIMESTAMP = 1767225600  # 对应 2026-01-01 00:00:00 UTC


def get_epoch(test_mode=False):
    """获取标准化的时间戳（兼容MicroPython非标准纪元）"""
    if test_mode:
        return TEST_TIMESTAMP
    maybe_time = time()
    if maybe_time < 946684801:  # 2000-01-01的时间戳
        maybe_time += 946684801
    return int(maybe_time)


def hotp(key, counter, digits=6):
    """生成HOTP验证码"""
    counter = struct.pack(">Q", counter)  # 打包为大端8字节无符号长整数
    mac = Sha1HMAC(key, counter).digest()
    offset = mac[-1] & 0x0F
    binary = struct.unpack(">L", mac[offset : offset + 4])[0] & 0x7FFFFFFF
    code = str(binary)[-digits:]
    return ((digits - len(code)) * "0") + code


# Base32编解码相关常量和函数
_b32alphabet = {
    0: b"A", 9: b"J", 18: b"S", 27: b"3",
    1: b"B", 10: b"K", 19: b"T", 28: b"4",
    2: b"C", 11: b"L", 20: b"U", 29: b"5",
    3: b"D", 12: b"M", 21: b"V", 30: b"6",
    4: b"E", 13: b"N", 22: b"W", 31: b"7",
    5: b"F", 14: b"O", 23: b"X",
    6: b"G", 15: b"P", 24: b"Y",
    7: b"H", 16: b"Q", 25: b"Z",
    8: b"I", 17: b"R", 26: b"2",
}

_b32tab = [v[0] for k, v in sorted(_b32alphabet.items())]
_b32rev = dict([(v[0], k) for k, v in _b32alphabet.items()])


def unhexlify(data):
    if len(data) % 2 != 0:
        raise ValueError("Odd-length string")
    return bytes([int(data[i : i + 2], 16) for i in range(0, len(data), 2)])


def b32encode(s):
    if not isinstance(s, bytes_types):
        raise TypeError("expected bytes, not %s" % s.__class__.__name__)
    quanta, leftover = divmod(len(s), 5)
    if leftover:
        s = s + bytes(5 - leftover)
        quanta += 1
    encoded = bytearray()
    for i in range(quanta):
        c1, c2, c3 = struct.unpack("!HHB", s[i * 5 : (i + 1) * 5])
        c2 += (c1 & 1) << 16
        c3 += (c2 & 3) << 8
        encoded += bytes([
            _b32tab[c1 >> 11], _b32tab[(c1 >> 6) & 0x1F],
            _b32tab[(c1 >> 1) & 0x1F], _b32tab[c2 >> 12],
            _b32tab[(c2 >> 7) & 0x1F], _b32tab[(c2 >> 2) & 0x1F],
            _b32tab[c3 >> 5], _b32tab[c3 & 0x1F],
        ])
    if leftover == 1:
        encoded = encoded[:-6] + b"======"
    elif leftover == 2:
        encoded = encoded[:-4] + b"===="
    elif leftover == 3:
        encoded = encoded[:-3] + b"==="
    elif leftover == 4:
        encoded = encoded[:-1] + b"="
    return bytes(encoded)


def b32decode(s):
    if isinstance(s, str):
        s = s.encode()
    quanta, leftover = divmod(len(s), 8)
    if leftover:
        raise ValueError("Incorrect padding")
    s = s.upper()
    padchars = s.find(b"=")
    if padchars > 0:
        padchars = len(s) - padchars
        s = s[:-padchars]
    else:
        padchars = 0

    parts = []
    acc = 0
    shift = 35
    for c in s:
        val = _b32rev.get(c)
        if val is None:
            raise ValueError("Non-base32 digit found")
        acc += _b32rev[c] << shift
        shift -= 5
        if shift < 0:
            parts.append(unhexlify(bytes("%010x" % acc, "ascii")))
            acc = 0
            shift = 35
    last = unhexlify(bytes("%010x" % acc, "ascii"))
    if padchars == 0:
        last = b""
    elif padchars == 1:
        last = last[:-1]
    elif padchars == 3:
        last = last[:-2]
    elif padchars == 4:
        last = last[:-3]
    elif padchars == 6:
        last = last[:-4]
    else:
        raise ValueError("Incorrect padding")
    parts.append(last)
    return b"".join(parts)


def generate_totp(secret, digits=6, time_step=30, test_mode=False):
    """
    生成TOTP动态验证码（对外暴露的核心接口）
    :param secret: Base32格式的密钥字符串（无需手动补=）
    :param digits: 验证码位数（默认6位）
    :param time_step: 验证码有效期（默认30秒）
    :param test_mode: 是否启用测试模式，默认False，使用真实时间
    :return: 字符串格式的TOTP验证码
    """
    # 自动补全Base32字符串到8的倍数长度（无需用户手动处理）
    padding_len = (8 - len(secret) % 8) % 8
    secret_padded = secret + '=' * padding_len
    
    try:
        # 解码Base32密钥为字节
        key_bytes = b32decode(secret_padded)
        # 计算时间计数器并生成验证码
        counter = get_epoch(test_mode=test_mode) // time_step
        return hotp(key_bytes, counter, digits)
    except Exception as e:
        raise ValueError(f"生成TOTP失败：{str(e)}")


# 测试示例（直接运行库文件时执行）
if __name__ == "__main__":
    # 示例：传入Base32密钥，获取验证码
    test_secret = 'PEFDAW3BQBA2CBBUB3AECPZXENYACEZXZIK2A7AWUM2LR7FF'
    try:
        totp_code = generate_totp(test_secret, test_mode=True)
        print(f"[测试模式] 当前TOTP验证码：{totp_code}")
        # 输出应为固定值（取决于密钥和时间步）
    except ValueError as e:
        print(f"错误：{e}")

    # 正常模式
    try:
        totp_code = generate_totp(test_secret, test_mode=False)
        print(f"[实时模式] 当前TOTP验证码：{totp_code}")
    except ValueError as e:
        print(f"错误：{e}")