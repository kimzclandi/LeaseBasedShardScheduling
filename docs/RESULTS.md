# 本地实验记录 · 2026-09-18

运行环境：Python 3.14.6，macOS arm64，系统报告 16 个逻辑 CPU。单机 loopback HTTP，协调器与 worker 为独立进程，SQLite 位于本地磁盘。代码使用 AI 辅助开发。

## 结果

- 27 项契约与 HTTP 边界测试通过。
- 每次输入 1,200 行 / 24 片；发布 1,000 条唯一有效记录、100 条重复映射、100 条隔离记录。
- 三轮单 worker 与四 worker 对照，以及一次四 worker 故障实验，共 7 次，输出 manifest SHA-256 相同：`1032ddaa5bafab4a5bab70182390b888ad6e990562044778fa52d03479e55ba5`。
- 故障实验实际杀掉一个已领取任务的 worker；任务到期重试，过期提交返回 409。
- 协调器实际 SIGKILL 并重启，相同提交重放成功。每次运行均恰好 24 条 committed 事件。

| 运行 | worker 进程数 | 故障注入 | 秒 | 各 worker 成功提交分片数 |
|---|---:|---|---:|---|
| 1 | 1 | 无 | 0.1323 | 24 |
| 2 | 4 | 无 | 0.1293 | 0, 1, 8, 15 |
| 3 | 4 | 无 | 0.1350 | 1, 9, 9, 5 |
| 4 | 1 | 无 | 0.1307 | 24 |
| 5 | 1 | 无 | 0.1343 | 24 |
| 6 | 4 | 无 | 0.1358 | 12, 3, 7, 2 |
| 7 | 4 | 有 | 0.4365 | 8, 4, 3, 8 |

单 worker 中位数 0.1323s；四 worker 中位数 0.1350s；观察到的速度比 0.980×。**此次四 worker 没有加速，不声称性能收益。** 任务很轻，进程启动、HTTP、SQLite 单写者和轮询开销占比较高；部分 worker 可能领不到任务，回执完整保留。三次重复不足以推断稳定性能差异。

计时从提交输入后的 worker 启动前开始，到所有 worker 退出为止，不包含首次 coordinator 启动、输入入库、最终 publish。故障运行包含重启与等待，不与无故障吞吐直接比较。无人工 per-row sleep，也未通过增加无意义计算制造加速。

## 复核

`python3 scripts/verify_evidence.py` 只校验已保存记录、行数、manifest、提交事件和源码身份，不重新执行故障。

`python3 scripts/demo.py --out runs/new-experiment --repeats 3` 在新目录重新运行。当前 [summary.json](../evidence/local/summary.json) 保存原始回执、计时和代码哈希；[故障事件](../evidence/local/fault/events.json) 与 [注入记录](../evidence/local/fault/fault_trace.json) 分开保存。JSON 来自自动运行，非手工编写测试结果。

## 未验证

多机通信、网络分区、断电、高可用、海量数据、对象存储、模型收益、语义质量与隐私脱敏均不在实验范围。SIGKILL 后已提交记录存续，不能外推任何断电条件下的持久性。外部副作用不属于 SQLite 幂等保证。
