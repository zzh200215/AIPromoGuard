"""探测当前 API key 上哪些模型可用（免费额度检测）。

用途：某个模型的免费额度用完后（调用报 Arrearage/配额错误），跑本脚本
看看 key 上还有哪些模型能用，然后把 .env 的 LLM_MODEL 换成可用模型。

原理：对候选模型各发一个 max_tokens=16 的最小调用——成功的即当前可用
（每个可用模型消耗约 20 token 免费额度，这是探测的必要成本）；欠费/配额类
错误即不可用。models 列表接口只反映"key 能看到哪些模型"，不代表有额度，
所以必须实调探测。

用法（仓库根目录）:
    python scripts/check_models.py                  # 探测默认候选清单
    python scripts/check_models.py --list flash     # 只列出名字含 flash 的模型
    python scripts/check_models.py --models qwen3.8-flash,qwen-flash
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from openai import OpenAI  # noqa: E402
from src.utils.config import settings  # noqa: E402
from src.utils.logger import get_logger  # noqa: E402

logger = get_logger(__name__)

# 按价格从低到高的常用文本生成模型（json_mode / function calling 均已验证兼容）
DEFAULT_CANDIDATES = [
    "qwen3.7-flash",
    "qwen3.8-flash",
    "qwen3.6-flash",
    "qwen3.5-flash",
    "qwen-flash",
    "qwen-turbo",
    "qwen3.7-plus",
    "qwen3.6-plus",
    "qwen-plus",
]

_SKIP_KEYWORDS = (
    "asr", "audio", "livetranslate", "mt", "omni", "coder", "tts", "vl-ocr",
    "embedding", "rerank", "image", "wan", "speech", "rumo", "deep-research",
)


def list_models(client: OpenAI, keyword: str | None = None) -> list[str]:
    models = sorted(m.id for m in client.models.list())
    if keyword:
        models = [m for m in models if keyword.lower() in m.lower()]
    return models


def text_models(client: OpenAI) -> list[str]:
    return [
        m for m in list_models(client)
        if not any(k in m.lower() for k in _SKIP_KEYWORDS)
    ]


def probe(client: OpenAI, model: str) -> tuple[bool, str]:
    """最小调用探测。返回 (是否可用, 说明)。"""
    try:
        r = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "回复两个字：可用"}],
            max_tokens=16,
            temperature=0,
        )
        text = (r.choices[0].message.content or "").strip()[:20]
        return True, text
    except Exception as e:
        return False, f"{type(e).__name__}: {str(e)[:70]}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models", default=None, help="逗号分隔的待探测模型（缺省用内置候选）")
    parser.add_argument(
        "--list", dest="list_kw", default=None, help="只列出名字含该关键词的模型，不探测"
    )
    parser.add_argument("--all", action="store_true", help="探测 key 下全部文本生成模型（较慢）")
    args = parser.parse_args()

    client = OpenAI(api_key=settings.dashscope_api_key, base_url=settings.llm_base_url)

    if args.list_kw:
        for m in list_models(client, args.list_kw):
            print(m)
        return 0

    candidates = (
        text_models(client)
        if args.all
        else [m.strip() for m in args.models.split(",")]
        if args.models
        else DEFAULT_CANDIDATES
    )

    print(f"当前 LLM_MODEL={settings.llm_model}，探测 {len(candidates)} 个候选：")
    usable: list[str] = []
    for model in candidates:
        ok, detail = probe(client, model)
        mark = "OK  " if ok else "FAIL"
        print(f"  {mark} {model:<20} {detail}")
        if ok:
            usable.append(model)

    print()
    if usable:
        if settings.llm_model in usable:
            print(f"当前模型 {settings.llm_model} 仍可用。")
        else:
            print(f"当前模型 {settings.llm_model} 不可用，可切换到（按列表顺序）：")
            for m in usable:
                print(f"  sed -i 's/^LLM_MODEL=.*/LLM_MODEL={m}/' .env   # → {m}")
    else:
        print("所有候选均不可用：免费额度可能已耗尽或账户欠费，请到百炼控制台确认。")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
