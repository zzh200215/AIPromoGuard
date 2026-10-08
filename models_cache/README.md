离线模型缓存注入点
==================

用途：docker/Dockerfile.api 的 embedding 模型预下载步骤（fastembed bge-small-zh-v1.5）
支持**离线优先**——构建前把本机缓存复制到构建上下文的 models_cache/ 即可跳过在线下载
（hf-mirror 等在线通道不稳定时的可靠路径）。

本目录内容不进 git（见 .gitignore），仅保留本说明与 .gitkeep 占位
（构建上下文需要该目录存在，哪怕为空——空则行为与历史一致：走在线下载）。

复制方法（Git Bash，在项目根执行）：

    mkdir -p models_cache
    (cd data/models/fastembed && tar cf - --exclude=.locks .) | (cd models_cache && tar xf -)

随后正常构建即可（构建脚本见 scripts/deploy/init_staging.py 的构建指引）。
