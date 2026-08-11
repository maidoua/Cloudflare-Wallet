# Cloudflare Wallet 名称可用性检测器

通过以下接口批量检测 Cloudflare Wallet 名称是否可用：

```text
GET https://cloudflare.pay/api/check?tag=YOURTAG
```

请仅在获得接口使用授权的情况下运行，并根据服务器响应调整请求速度。

## 运行环境

- Windows PowerShell
- Python 3
- 不需要安装第三方 Python 依赖

本项目的 `run.ps1` 会优先使用 Codex 自带的 Python；也可以安装 Python 3
并将 `python.exe` 加入系统 `PATH`。

## 快速开始

在 VS Code PowerShell 终端运行：

```powershell
.\run.ps1 --length 3 --category all
```

也可以双击 `run.cmd`。运行结束或报错后，窗口会保持打开。

建议首次运行时只检测少量名称：

```powershell
.\run.ps1 --length 3 --category all --limit 20
```

## 组合扫描

检测所有 3 位数字和小写字母组合：

```powershell
.\run.ps1 --length 3 --category all --workers 16 --batch-size 200
```

按类型分别检测：

```powershell
# 纯数字，例如 001、888
.\run.ps1 --length 3 --category numeric

# 纯小写字母，例如 app、web
.\run.ps1 --length 3 --category alpha

# 数字和小写字母混合，例如 a12、03f
.\run.ps1 --length 3 --category mixed
```

`--category all` 包含纯数字、纯字母和数字字母混合的全部组合。

## 按词库顺序扫描

使用文本文件中的名称逐行检测：

```powershell
.\run.ps1 --input-file ".\ku\merged_unique_min3.txt" --workers 16 --batch-size 200
```

名称会按输入文件的行顺序提交。多线程的完成顺序可能不同，但每批保存前会
恢复为词库顺序；中断续跑或失败重试后也会重新排序。

词库扫描默认使用独立结果目录，例如：

```text
results/merged_unique_min3_ordered/
```

这样不会与组合扫描的历史结果混合。

## 输出文件

- `available.txt`：可用名称
- `reserved.txt`：已占用或被接口规则拒绝的名称
- `errors.jsonl`：重试后仍然失败的请求记录

默认只在终端显示可用名称。需要同时显示已占用名称时添加：

```powershell
--show-reserved
```

结果采用批量追加写入。重新运行相同命令时，已存在于 `available.txt` 或
`reserved.txt` 的名称会自动跳过，实现断点续跑。

## 常用参数

| 参数 | 默认值 | 说明 |
| --- | ---: | --- |
| `--delay` | `0.001` | 所有线程之间的全局请求启动间隔，单位为秒 |
| `--workers` | `8` | 并发请求线程数 |
| `--batch-size` | `100` | 每批检测并保存的名称数量 |
| `--timeout` | `10` | 单次请求超时秒数 |
| `--retries` | `4` | 临时失败和限流的重试次数 |
| `--limit` | 无 | 本次最多检测多少个未完成名称 |
| `--progress-every` | `25` | 每完成多少个名称显示一次进度 |
| `--output-dir` | 自动 | 指定结果保存目录 |

查看全部参数：

```powershell
.\run.ps1 --help
```

## 速度与稳定性

默认 `--delay 0.001` 速度较快，实际吞吐量仍受线程数、网络延迟和服务器限制。
如果出现大量 `429`、`403`、SSL 断连或最终错误，请降低速度，例如：

```powershell
.\run.ps1 --input-file ".\ku\merged_unique_min3.txt" --workers 8 --delay 0.02
```

每个线程都会复用持久 HTTPS 连接，并在服务器关闭连接后自动重连一次，以
减少重复 TLS 握手和临时 SSL EOF 错误。不要同时启动多个扫描进程写入同一
结果目录，否则可能产生重复请求或文件写入冲突。

接口返回 `HTTP 400` 时，该名称会被视为不可用并保存到 `reserved.txt`。
认证错误、限流和服务器错误不会被错误地标记为已占用。

---

# Cloudflare Wallet Tag Availability Checker

Batch-check Cloudflare Wallet tag availability through:

```text
GET https://cloudflare.pay/api/check?tag=YOURTAG
```

Only use this tool when you are authorized to access the endpoint. Adjust the
request rate according to the server response.

## Requirements

- Windows PowerShell
- Python 3
- No third-party Python packages

`run.ps1` first looks for the Python runtime bundled with Codex. Alternatively,
install Python 3 and make sure `python.exe` is available on `PATH`.

## Quick Start

Run from a VS Code PowerShell terminal:

```powershell
.\run.ps1 --length 3 --category all
```

You can also double-click `run.cmd`. Its window remains open after the scan
finishes or reports an error.

Start with a small sample:

```powershell
.\run.ps1 --length 3 --category all --limit 20
```

## Generated Combinations

Check every three-character lowercase alphanumeric combination:

```powershell
.\run.ps1 --length 3 --category all --workers 16 --batch-size 200
```

Check categories separately:

```powershell
# Numeric only, such as 001 and 888
.\run.ps1 --length 3 --category numeric

# Lowercase letters only, such as app and web
.\run.ps1 --length 3 --category alpha

# Mixed digits and lowercase letters, such as a12 and 03f
.\run.ps1 --length 3 --category mixed
```

`--category all` includes numeric, alphabetic, and mixed combinations.

## Ordered Word-List Scan

Check tags from a text file in line order:

```powershell
.\run.ps1 --input-file ".\ku\merged_unique_min3.txt" --workers 16 --batch-size 200
```

Requests are submitted in source-file order. Workers may complete out of order,
but each batch is reordered before being saved. The same ordering is restored
after an interrupted run or a successful retry.

Word-list scans use a dedicated result directory by default, for example:

```text
results/merged_unique_min3_ordered/
```

This prevents older combination-scan results from affecting the requested
order.

## Output Files

- `available.txt`: available tags
- `reserved.txt`: reserved tags and tags rejected by validation rules
- `errors.jsonl`: requests that still failed after all retries

Only available tags are printed by default. Add the following option to print
reserved tags too:

```powershell
--show-reserved
```

Results are appended in batches. Running the same command again skips tags
already stored in `available.txt` or `reserved.txt`, providing resumable scans.

## Options

| Option | Default | Description |
| --- | ---: | --- |
| `--delay` | `0.001` | Global interval between request starts, in seconds |
| `--workers` | `8` | Number of concurrent request workers |
| `--batch-size` | `100` | Number of results processed and saved per batch |
| `--timeout` | `10` | Request timeout in seconds |
| `--retries` | `4` | Retries for temporary failures and rate limits |
| `--limit` | None | Maximum number of unfinished tags to check this run |
| `--progress-every` | `25` | Progress reporting interval |
| `--output-dir` | Automatic | Custom result directory |

Show every option:

```powershell
.\run.ps1 --help
```

## Performance and Reliability

The default `--delay 0.001` is aggressive. Actual throughput is limited by the
worker count, network latency, and server-side controls. If you see frequent
`429`, `403`, SSL disconnects, or final errors, reduce the request rate:

```powershell
.\run.ps1 --input-file ".\ku\merged_unique_min3.txt" --workers 8 --delay 0.02
```

Each worker reuses a persistent HTTPS connection and reconnects once when the
server closes it. This reduces repeated TLS handshakes and transient SSL EOF
errors. Do not run multiple scanner processes against the same output directory;
doing so can cause duplicate requests or conflicting file writes.

An `HTTP 400` response is treated as an unavailable tag and stored in
`reserved.txt`. Authentication failures, rate limits, and server failures are
not incorrectly marked as reserved.
