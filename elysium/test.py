import os
import glob

# 要清理的目录路径
directory_to_zip = '../elysium/2024/10/30'

# 构建搜索模式，匹配所有非 .sol 文件
pattern = os.path.join(directory_to_zip, '*')

# 使用 glob.glob 遍历所有匹配的文件
for file_path in glob.glob(pattern):
    # 检查文件扩展名是否不是 .sol
    if not file_path.endswith('.sol'):
        # 删除文件
        os.remove(file_path)
        print(f"Deleted file: {file_path}")