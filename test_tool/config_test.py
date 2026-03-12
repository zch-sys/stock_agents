# detailed_config_check.py
import os
import sys

PROJECT_ROOT = "E:\\tradingagents"
config_path = os.path.join(PROJECT_ROOT, "config", "settings.yaml")

print(f"配置文件路径: {config_path}")
print(f"文件大小: {os.path.getsize(config_path)} 字节")

# 以二进制读取文件
with open(config_path, 'rb') as f:
    raw_data = f.read()

print("\n=== 二进制分析 ===")
print(f"前100字节(十六进制):")
for i in range(0, min(100, len(raw_data)), 16):
    hex_str = ' '.join(f'{b:02x}' for b in raw_data[i:i+16])
    ascii_str = ''.join(chr(b) if 32 <= b < 127 else '.' for b in raw_data[i:i+16])
    print(f"{i:04x}: {hex_str:<48} {ascii_str}")

print("\n=== BOM检查 ===")
# 检查常见的BOM
bom_types = {
    b'\xef\xbb\xbf': 'UTF-8 BOM',
    b'\xfe\xff': 'UTF-16 BE',
    b'\xff\xfe': 'UTF-16 LE',
    b'\x00\x00\xfe\xff': 'UTF-32 BE',
    b'\xff\xfe\x00\x00': 'UTF-32 LE',
}

for bom, name in bom_types.items():
    if raw_data.startswith(bom):
        print(f"检测到 {name}")
        print(f"BOM十六进制: {bom.hex()}")
        break
else:
    print("未检测到BOM")

print("\n=== 编码尝试 ===")
encodings = ['utf-8', 'utf-8-sig', 'gbk', 'gb2312', 'latin-1', 'cp1252']

for enc in encodings:
    try:
        decoded = raw_data.decode(enc)
        # 检查是否包含YAML关键字
        if 'data_collector:' in decoded:
            print(f"✓ {enc}: 成功解码，包含 'data_collector:'")
            # 显示前几行
            lines = decoded.split('\n')[:5]
            print(f"  前5行: {[repr(line) for line in lines]}")
        else:
            print(f"  {enc}: 解码成功但未找到 'data_collector:'")
    except UnicodeDecodeError as e:
        print(f"✗ {enc}: 解码失败 - {e}")
        # 显示错误位置
        error_idx = e.start
        if error_idx < len(raw_data):
            print(f"    错误位置 {error_idx}: 字节值 {raw_data[error_idx]:02x}")
            # 显示上下文
            start = max(0, error_idx - 10)
            end = min(len(raw_data), error_idx + 10)
            context = raw_data[start:end]
            print(f"    上下文: {context.hex()}")

print("\n=== 尝试清理文件 ===")
# 尝试清理可能损坏的UTF-8
def clean_utf8(raw_bytes):
    result = bytearray()
    i = 0
    while i < len(raw_bytes):
        byte = raw_bytes[i]
        if byte < 0x80:  # ASCII字符
            result.append(byte)
            i += 1
        elif 0xC0 <= byte < 0xE0 and i + 1 < len(raw_bytes):  # 2字节UTF-8
            if 0x80 <= raw_bytes[i+1] < 0xC0:
                result.append(byte)
                result.append(raw_bytes[i+1])
                i += 2
            else:
                # 无效的第二字节，跳过
                i += 1
        elif 0xE0 <= byte < 0xF0 and i + 2 < len(raw_bytes):  # 3字节UTF-8
            if (0x80 <= raw_bytes[i+1] < 0xC0 and 
                0x80 <= raw_bytes[i+2] < 0xC0):
                result.append(byte)
                result.append(raw_bytes[i+1])
                result.append(raw_bytes[i+2])
                i += 3
            else:
                i += 1
        elif 0xF0 <= byte < 0xF8 and i + 3 < len(raw_bytes):  # 4字节UTF-8
            if (0x80 <= raw_bytes[i+1] < 0xC0 and 
                0x80 <= raw_bytes[i+2] < 0xC0 and
                0x80 <= raw_bytes[i+3] < 0xC0):
                result.append(byte)
                result.append(raw_bytes[i+1])
                result.append(raw_bytes[i+2])
                result.append(raw_bytes[i+3])
                i += 4
            else:
                i += 1
        else:
            # 无效的UTF-8起始字节，跳过
            i += 1
    return bytes(result)

cleaned = clean_utf8(raw_data)
print(f"清理后字节数: {len(cleaned)} (原始: {len(raw_data)})")

try:
    decoded_cleaned = cleaned.decode('utf-8')
    print("✓ 清理后UTF-8解码成功")
    # 查找配置内容
    if 'data_collector:' in decoded_cleaned:
        print("  包含配置内容")
        # 保存清理后的文件
        backup_path = config_path + '.backup'
        with open(backup_path, 'wb') as f:
            f.write(raw_data)
        print(f"  原始文件已备份到: {backup_path}")
        
        # 写入清理后的文件
        with open(config_path, 'wb') as f:
            f.write(cleaned)
        print("✅ 已修复配置文件")
    else:
        print("  清理后文件不包含配置内容")
except Exception as e:
    print(f"✗ 清理后UTF-8解码失败: {e}")

print("\n=== 尝试Latin-1解码（不会失败） ===")
try:
    latin1_decoded = raw_data.decode('latin-1')
    print(f"Latin-1解码成功，长度: {len(latin1_decoded)} 字符")
    # 查找YAML内容
    lines = latin1_decoded.split('\n')
    for i, line in enumerate(lines):
        if 'data_collector:' in line:
            print(f"  在第{i+1}行找到 'data_collector:'")
            print(f"  行内容: {repr(line)}")
            # 显示上下文
            for j in range(max(0, i-2), min(len(lines), i+3)):
                prefix = '>>>' if j == i else '   '
                print(f"{prefix} {j+1:3d}: {repr(lines[j])}")
            break
    else:
        print("  未找到 'data_collector:'")
except Exception as e:
    print(f"Latin-1解码也失败: {e}")