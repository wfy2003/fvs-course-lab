# 基于 SSD 的过滤向量检索系统课程实验

本仓库提供课程实验说明、统一 YFCC 课程数据集下载入口，以及 PipeANN-Filter、GateANN、Filtered-DiskANN 三套系统的命令适配器。数据集和第三方系统源码不直接存入 Git 仓库。

## 快速开始

### 1. 克隆课程仓库

```bash
git clone <COURSE_REPOSITORY_URL> fvs-course-lab
cd fvs-course-lab
```

### 2. 下载并校验数据集

```bash
bash scripts/download_dataset.sh
```

数据集将解压到 `datasets/yfcc_course_v1/`。Debug 数据包含 10 万个 Base 向量，用于调试；Formal 数据包含 100 万个 Base 向量，用于正式实验。

### 3. 准备所选系统

学生从 PipeANN-Filter、GateANN 和 Filtered-DiskANN 中选择一个系统，并使用课程指定版本。版本信息见 `adapters/versions.json`。

```text
PipeANN-Filter:    thustorage/PipeANN
GateANN:           GyuyeongKim/GateANN-public
Filtered-DiskANN:  microsoft/DiskANN（cpp_main 分支）
```

系统源码可以放在任意位置；运行适配器时通过 `--repo` 指定。不要将第三方系统源码、构建产物或实验索引提交到课程仓库。

### 4. 先在 Debug 数据上检查

以 PipeANN-Filter 为例：

```bash
python3 adapters/pipeann_adapter.py doctor \
  --repo /path/to/PipeANN \
  --dataset-root "$PWD/datasets/yfcc_course_v1" \
  --tier debug
```

构建索引并查询：

```bash
python3 adapters/pipeann_adapter.py build \
  --repo /path/to/PipeANN \
  --dataset-root "$PWD/datasets/yfcc_course_v1" \
  --tier debug \
  --run-root "$PWD/course_runs" \
  --threads 8

python3 adapters/pipeann_adapter.py search \
  --repo /path/to/PipeANN \
  --dataset-root "$PWD/datasets/yfcc_course_v1" \
  --tier debug \
  --run-root "$PWD/course_runs" \
  --bucket medium \
  --threads 1 --beamwidth 8 --k 10 --L 20 40 80
```

GateANN 和 Filtered-DiskANN 只需替换适配器文件及 `--repo` 路径：

```text
adapters/gateann_adapter.py
adapters/filtered_diskann_adapter.py
```

所有系统统一输出 `command.json`、`run.log` 和 `results.csv`。索引与结果默认保存在 `course_runs/`，该目录不会被 Git 跟踪。

## 仓库内容

```text
fvs-course-lab/
├── README.md
├── .gitignore
├── adapters/                 # 三系统构建、查询和结果归一化适配器
├── config/dataset.env        # 教师填写数据集 URL 和 SHA-256
├── datasets/README.md        # 数据目录说明，不包含数据本体
├── docs/实验说明.md
└── scripts/
    ├── download_dataset.sh
    └── check_dataset.sh
```

## 实验入口

- 正式任务、测试要求与提交内容：`docs/实验说明.md`
- 固定源码版本、预期二进制和依赖提示：`docs/系统准备.md`
- 适配器参数帮助：`python3 adapters/<system>_adapter.py --help`
- 数据完整性检查：`bash scripts/check_dataset.sh`

## 教师发布前检查

1. 在 `config/dataset.env` 中填写数据集下载地址和压缩包 SHA-256。
2. 确认数据包顶层目录名为 `yfcc_course_v1`。
3. 确认课程指定系统提交与 `adapters/versions.json` 一致。
4. 在一台干净环境中完成一次 `clone -> download -> doctor` 测试。
5. 为公开或校外发布补充适当的仓库许可证及 YFCC 数据引用信息。

