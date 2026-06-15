from __future__ import annotations

import re


def get_compact_prompt(custom_instructions: str | None = None) -> str:
    prompt = """你的任务是创建一份详细的对话摘要。摘要将替换被压缩的旧消息，保留关键信息以便后续继续工作。

在给出最终摘要之前，请用 <analysis> 标签整理你的思路：

1. 逐条分析每条消息，识别：
   - 用户的具体请求和意图
   - 你对请求的回应和采取的行动
   - 关键决策和技术细节
   - 涉及的产品名称、文件、数据来源
   - 遇到的错误和修复方式
   - 用户的反馈或纠正

2. 确保覆盖所有重要细节，不要遗漏。

最终摘要必须包含以下部分：

1. 用户请求和意图：用户本次研究的主要目标和具体问题
2. 涉及产品：讨论的所有保险产品名称、别名
3. 关键发现：重要的证据、数据、条款内容
4. 使用来源：访问了哪些数据源（官网、本地资料、搜索结果等）
5. 错误和处理：遇到的错误及解决方式
6. 待办事项：明确要求但尚未完成的任务
7. 当前状态：压缩前正在处理的最后工作

示例输出格式：

<analysis>
[你的思考过程]
</analysis>

<summary>
1. 用户请求和意图：
   [详细描述]

2. 涉及产品：
   - 产品A
   - 产品B

3. 关键发现：
   - [重要发现1]
   - [重要发现2]

4. 使用来源：
   - [来源1]
   - [来源2]

5. 错误和处理：
   - [错误描述] → [处理方式]

6. 待办事项：
   - [待办1]

7. 当前状态：
   [最近正在处理的工作描述]
</summary>"""

    if custom_instructions:
        prompt += f"\n\n附加说明：\n{custom_instructions}"

    prompt += "\n\n重要：只返回文本，不要调用任何工具。"
    return prompt


def get_iterative_compact_prompt(custom_instructions: str | None = None) -> str:
    prompt = """你有一个已有的对话摘要和新的对话历史。你的任务是将两者合并且创建一个单一的、连贯的、更新的摘要，覆盖已有摘要和新内容中的全部信息。

在给出最终摘要之前，请用 <analysis> 标签整理你的思路：

1. 分析已有摘要中涵盖了哪些信息
2. 分析新对话中增加了哪些信息、决策、发现
3. 确定如何将两者合并，去重并保持连贯

最终摘要必须包含以下部分（与已有格式保持一致）：

1. 用户请求和意图
2. 涉及产品
3. 关键发现
4. 使用来源
5. 错误和处理
6. 待办事项
7. 当前状态

示例输出格式：

<analysis>
[你的合并思路]
</analysis>

<summary>
1. 用户请求和意图：
   [合并后的描述]

2. 涉及产品：
   - 产品A
   - 产品B

3. 关键发现：
   - [重要发现1]
   ...

4. 使用来源：
   - [来源1]
   ...

5. 错误和处理：
   - [错误描述] → [处理方式]

6. 待办事项：
   - [待办1]

7. 当前状态：
   [最近正在处理的工作描述]
</summary>"""

    if custom_instructions:
        prompt += f"\n\n附加说明：\n{custom_instructions}"

    prompt += "\n\n重要：只返回文本，不要调用任何工具。"
    return prompt


def format_compact_summary(summary: str) -> str:
    formatted = re.sub(r'<analysis>[\s\S]*?</analysis>', '', summary)

    match = re.search(r'<summary>([\s\S]*?)</summary>', formatted)
    if match:
        content = match.group(1) or ''
        formatted = re.sub(
            r'<summary>[\s\S]*?</summary>',
            f'对话摘要：\n{content.strip()}',
            formatted,
        )

    formatted = re.sub(r'\n{3,}', '\n\n', formatted)
    return formatted.strip()
