"""命令行演示：python agent-service/examples/run_real_agent.py "推荐运动鞋并查看第一款详情"""

import argparse
import json
import time

from react_agent import run_react
from real_llm import ModelCallError, RealLLM


def main():
    parser = argparse.ArgumentParser(description="运行第三课真实模型 ReAct 示例")
    parser.add_argument("question", nargs="?", help="用户问题；省略时交互输入")
    args = parser.parse_args()
    question = args.question or input("请输入问题：")
    try:
        llm = RealLLM()
    except ModelCallError as exc:
        parser.exit(2, f"模型配置错误：{exc.code}\n")
    started = time.perf_counter()
    result = run_react(question, llm=llm)
    for record in result["trace"]:
        print(f'第 {record["step"]} 轮：{json.dumps(record.get("model_output", {"error": record.get("error")}), ensure_ascii=False)}')
        if "observation" in record:
            print("Observation：" + json.dumps(record["observation"], ensure_ascii=False))
    print("最终回答：" + result["answer"])
    print(f'模型调用次数：{len(result["trace"])}；总耗时：{time.perf_counter() - started:.2f} 秒')
    if result["error"]:
        parser.exit(1, f'运行状态：{result["error"]}\n')


if __name__ == "__main__":
    main()
