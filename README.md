# AI Data Shard Lab · 数据分片处理与故障恢复

[![reliability-contracts](https://github.com/kimzclandi/ai-data-shard-lab/actions/workflows/ci.yml/badge.svg)](https://github.com/kimzclandi/ai-data-shard-lab/actions/workflows/ci.yml)

**一个 worker 处理完数据却没有收到提交响应，再重试会发生什么？一个过期 worker 恢复后，能否覆盖新结果？**

本项目用 Python 标准库实现一个小型 AI 文本数据处理实验：HTTP 协调器分配分片，独立 worker 进程完成文本规范化和基础质量检查，SQLite 保存租约、提交结果和事件，最终发布带来源哈希的确定性数据清单。

**已验证范围：单机、多进程、loopback HTTP、合成文本。** 实现分布式任务处理中常见的租约、fencing 和幂等机制，但没有多机部署、分布式存储、共识协议或生产规模验证。没有模型训练，基础清洗规则不代表语义质量评估。

## 三分钟检查

需要 Python 3.12+、macOS 或 Linux；无第三方运行依赖、模型下载或付费 API。

```bash
git clone https://github.com/kimzclandi/ai-data-shard-lab.git
cd ai-data-shard-lab
python3 -m unittest discover -s tests -v
python3 scripts/verify_evidence.py
python3 scripts/demo.py --out runs/my-first-run --repeats 1
```

`--out` 必须是新目录，避免覆盖已有实验。最后一个命令启动真实 HTTP 服务及 worker 子进程，自动注入故障，并在退出时清理进程。数据库和 JSON 保留在指定目录；仅监听 `127.0.0.1`。服务默认使用临时端口，不对外部署。

| 检查入口 | 看什么 |
|---|---|
| [实验报告](docs/RESULTS.md) | 运行环境、计时、故障结果与限制 |
| [保存的原始记录](evidence/local/summary.json) | 每次运行、worker 回执、源文件哈希 |
| [架构与语义](docs/ARCHITECTURE.md) | 状态机、事务边界、租约与 fencing |
| [代码审查路径](docs/REVIEW.md) | 五个关键实现和反例 |
| [测试](tests/test_core.py) | 并发领取、过期提交、故障恢复、跨分片去重 |

## 输入、处理与产物

- 输入：1,200 条固定合成文本记录，划分为 24 个分片。包含 1,000 条唯一有效记录、100 条重复记录、100 条空白/类型错误记录。
- worker：NFKC 与空白规范化、字符串类型及最短长度检查；每行输出原始记录哈希、稳定行 ID 和接受/隔离原因。
- 协调器：租约到期重试、递增 attempt token、条件提交、持久事件记录。收到相同提交可以重放确认，不同结果拒绝覆盖。
- 发布：所有分片成功后才可发布；按行 ID 确定重复记录保留者，输出有效数据、隔离记录、重复映射与来源哈希。结果不依赖 worker 完成顺序。

## 故障验证

实验比较一个 worker、四个 worker，以及带故障的四个 worker。故障包含 worker 领取后被 SIGKILL、协调器在提交完成后被 SIGKILL 并重启、重复提交、旧租约提交。所有运行应生成同一份 manifest。

这是**可重试执行 + 数据库内幂等提交**，不是通用的 exactly-once execution。过期任务可执行多次；文件写入、模型调用和其他外部副作用不在事务保证内。

## 边界与下一步

- SQLite 与发布阶段都是单节点瓶颈；没有 HA、网络分区或机器断电验证。
- worker 是可信进程；哈希用于身份与损坏检查，不能防止恶意 worker 伪造合法结果。
- API 只服务本机实验，没有认证/TLS/多租户隔离，不能暴露到公网。
- 批量输入和 manifest 在内存处理；不适合海量数据。精确去重不能代替语义去重或训练/测试污染检测。
- 小任务可能因 HTTP 与事务开销变慢；计时只描述当前机器，不外推线性扩展能力。
- 真正扩展前应增加对象存储、生产队列/数据库、负载与故障矩阵，再考虑多机部署；这些尚未实现。

项目于 2026-09-18 开始。代码、测试与文档使用 AI 辅助开发；本实验仅验证单机多进程行为，未验证多机部署或生产负载。代码与合成样例：[MIT](LICENSE)。
