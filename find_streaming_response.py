with open('download.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()
    
for i, line in enumerate(lines, 1):
    if 'StreamingResponse(' in line:
        print(f'{i}: {line.strip()}')
        # 打印附近几行
        start = max(0, i-5)
        end = min(len(lines), i+10)
        for j in range(start, end):
            print(f'{j:3}: {lines[j].rstrip()}')
        print()